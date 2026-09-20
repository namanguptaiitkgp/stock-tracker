"""Gemini-powered peer discovery with persistent bidirectional storage.

Flow:
1. Gemini suggests 6-8 peers freely
2. Auto-fetch each from yfinance, cross-check industry to filter hallucinations
3. Industry scan from DB to find real peers Gemini missed
4. Second Gemini call to rank the merged real list → final 6-8 best peers
5. Store bidirectionally
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, desc, func, select, union_all
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gemini_client import call_gemini_with_rotation
from app.models.fundamentals import StockFundamentals
from app.models.stock_peers import StockPeer
from app.models.user import User

logger = logging.getLogger(__name__)

PEER_PROMPT = """\
You are an Indian equity market analyst. Identify 6–8 true peer companies for
{symbol} ({name}).

Company profile:
- Sector: {sector}
- Industry: {industry}
- Market cap: ₹{market_cap_display} ({cap_category})

Definition of a "true peer":
1. SAME SUB-INDUSTRY — not adjacent. A private bank's peer is another private
   bank, not an NBFC, insurance company, or payments fintech. A tyre maker's
   peer is another tyre maker, not an auto-ancillary broadly.
2. COMPARABLE SCALE — prefer within ~3× market cap, but for niche industries
   with few listed players (e.g. tyres, exchanges, defence), include ALL
   industry participants regardless of cap difference.
3. SIMILAR BUSINESS MODEL — same revenue mix (B2B vs B2C, product vs platform,
   domestic vs export). A domestic pharma formulator is not a peer to a
   CRAMS/CDMO export house.
4. DIRECT COMPETITOR or close substitute in the same value chain position
   (not supplier/customer).
5. LISTED ON NSE IN THE EQ (equity) SERIES — actively traded on the NSE
   cash market. Do NOT suggest BSE-only listings, SME-segment symbols, or
   trust/InvIT/REIT/ETF symbols. The symbol must be an NSE common-equity
   ticker.

Special cases:
- If the company is a near-monopoly (e.g. IRCTC, CDSL, IEX), say so and
  suggest the closest functional comparables even if imperfect. Label them
  as "closest comparable (not a direct peer)."
- If the company is a conglomerate subsidiary, compare the subsidiary's
  primary business, not the parent.
- PSU vs private distinction matters for valuation — include both if relevant
  but note the distinction.

Return ONLY valid JSON:
{{
  "peers": [
    {{"symbol": "NSE_SYMBOL", "rationale": "one line explaining why this is a peer"}}
  ],
  "notes": "any caveats about peer selection for this stock (optional, can be null)"
}}

Use NSE trading symbols (e.g. HDFCBANK, RELIANCE, TCS). Return 6–8 peers,
ordered by relevance (closest peer first)."""


RANK_PROMPT = """\
You are an Indian equity market analyst. I need you to pick the 6–8 best peer
companies for {symbol} ({name}) from the VERIFIED list below.

Target company:
- Sector: {sector}
- Industry: {industry}
- Market cap: ₹{market_cap_display} ({cap_category})

VERIFIED CANDIDATES (all real NSE-listed companies):
{candidates_block}

IMPORTANT: Pick ONLY companies in the SAME specific sub-industry as {symbol}.
For example:
- If {symbol} is a tyre manufacturer, pick ONLY other tyre manufacturers,
  NOT generic auto parts companies like brake/glass/electronics makers.
- If {symbol} is a jewellery retailer, pick ONLY other jewellery retailers,
  NOT generic luxury goods companies.

The industry classification "{industry}" may be broad — use your knowledge
of each company's actual business to pick true peers.

Pick the best peers, ranked by relevance (closest peer first). Aim for
6–8 but only if real sub-industry peers exist for them — **it is better
to return 3 true peers than 8 with 5 adjacent-industry filler**. The peer
set will be displayed verbatim to the user; do not include companies you
wouldn't defend as comparables.

Every returned `symbol` MUST be an NSE-listed common equity in the EQ
series — exclude BSE-only listings, SME-segment symbols, and
trust/InvIT/REIT/ETF tickers.

Return ONLY valid JSON:
{{
  "peers": [
    {{"symbol": "NSE_SYMBOL", "rationale": "one line explaining why this is a peer"}}
  ],
  "notes": "any caveats (optional, can be null)"
}}"""


def _cap_category(market_cap_cr: float | None) -> str:
    if market_cap_cr is None:
        return "unknown"
    if market_cap_cr >= 50_000:
        return "Large Cap"
    if market_cap_cr >= 10_000:
        return "Mid Cap"
    return "Small Cap"


def _fmt_cap(market_cap_cr: float | None) -> str:
    if market_cap_cr is None:
        return "unknown"
    if market_cap_cr >= 1_00_000:
        return f"{market_cap_cr / 1_00_000:.1f}L Cr"
    if market_cap_cr >= 1_000:
        return f"{market_cap_cr / 1_000:.1f}K Cr"
    return f"{market_cap_cr:,.0f} Cr"


async def generate_peers(
    symbol: str, db: AsyncSession, user: User,
) -> dict:
    from app.observability.activity import ai_purpose

    symbol = symbol.upper().strip()

    async with ai_purpose("peer_discovery", symbol=symbol, user_id=user.id):
        return await _generate_peers_inner(symbol, db, user)


async def _generate_peers_inner(
    symbol: str, db: AsyncSession, user: User,
) -> dict:

    fund = (
        await db.execute(
            select(StockFundamentals).where(StockFundamentals.symbol == symbol)
        )
    ).scalar_one_or_none()

    name = fund.name if fund else symbol
    sector = fund.sector if fund else "unknown"
    industry = fund.industry if fund else "unknown"
    market_cap = fund.market_cap if fund else None

    # ── Step 1: Gemini suggests peers freely ──
    prompt = PEER_PROMPT.format(
        symbol=symbol,
        name=name,
        sector=sector,
        industry=industry or sector or "unknown",
        market_cap_display=_fmt_cap(market_cap),
        cap_category=_cap_category(market_cap),
    )

    raw = await call_gemini_with_rotation(user.id, db, prompt)

    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not json_match:
        raise ValueError(f"Gemini returned no valid JSON for peer discovery of {symbol}")

    parsed = json.loads(json_match.group())
    raw_peers = parsed.get("peers", [])
    gemini_notes = parsed.get("notes")

    # ── Step 2: Validate Gemini suggestions via yfinance ──
    gemini_validated: dict[str, str] = {}  # symbol → rationale
    skipped: list[str] = []

    if raw_peers:
        sym_list = [p["symbol"].upper().strip() for p in raw_peers if p["symbol"].upper().strip() != symbol]

        # Check which already exist in DB
        result = await db.execute(
            select(StockFundamentals).where(
                StockFundamentals.symbol.in_(sym_list)
            )
        )
        existing = {f.symbol: f for f in result.scalars().all()}

        # Auto-fetch missing ones from yfinance.
        # IMPORTANT: each peer fetches in its own session. `get_fundamentals`
        # does `db.add(record)` without immediate flush — if a row violates
        # a NUMERIC column constraint (see fundamentals_validation /
        # NumericValueOutOfRangeError on yfinance garbage), the flush
        # happens on the NEXT iteration's `db.execute()` and poisons that
        # iteration's session with `PendingRollbackError`. Using a fresh
        # session per peer means one bad symbol can't cascade into the
        # next four peer fetches or the parent ASTRAL warmup.
        missing = [s for s in sym_list if s not in existing]
        if missing:
            from app.db.session import async_session
            from app.services.fundamentals_service import get_fundamentals
            for ms in missing:
                try:
                    async with async_session() as fresh_db:
                        rec = await get_fundamentals(ms, fresh_db, exchange="NSE", user_id=user.id)
                    if rec:
                        # The fresh session committed and is now closed; re-read
                        # the row on the caller's session so it can be referenced
                        # by downstream queries within the same transaction.
                        result_rec = await db.execute(
                            select(StockFundamentals).where(StockFundamentals.symbol == ms)
                        )
                        rec_caller = result_rec.scalar_one_or_none()
                        if rec_caller:
                            existing[ms] = rec_caller
                            logger.info("peer_discovery: auto-fetched fundamentals for %s", ms)
                except Exception as e:
                    logger.warning("peer_discovery: failed to fetch %s: %s", ms, e)

        # Cross-check industry — keep if same industry/sector or if industry is unknown
        target_industry = (industry or "").lower()
        target_sector = (sector or "").lower()

        for p in raw_peers:
            sym = p["symbol"].upper().strip()
            if sym == symbol:
                continue
            f = existing.get(sym)
            if not f:
                skipped.append(sym)
                continue

            peer_industry = (f.industry or "").lower()
            peer_sector = (f.sector or "").lower()

            # Accept if: same industry, same sector, or industry data missing
            if (target_industry and peer_industry and target_industry == peer_industry) \
               or (target_sector and peer_sector and target_sector == peer_sector) \
               or not target_industry or not peer_industry:
                gemini_validated[sym] = p.get("rationale", "")
            else:
                logger.info(
                    "peer_discovery: %s — filtered %s (industry mismatch: %s vs %s)",
                    symbol, sym, target_industry, peer_industry,
                )
                skipped.append(sym)

    if skipped:
        logger.warning(
            "peer_discovery: %s — skipped %d Gemini suggestions: %s",
            symbol, len(skipped), ", ".join(skipped),
        )

    # ── Step 3: Industry scan from DB ──
    industry_peers: dict[str, str] = {}  # symbol → name

    if industry:
        ind_result = await db.execute(
            select(StockFundamentals.symbol, StockFundamentals.name)
            .where(
                StockFundamentals.industry == industry,
                StockFundamentals.symbol != symbol,
            )
        )
        for row in ind_result.all():
            if row.symbol not in gemini_validated:
                industry_peers[row.symbol] = row.name or row.symbol

    if sector and len(gemini_validated) + len(industry_peers) < 6:
        sec_result = await db.execute(
            select(StockFundamentals.symbol, StockFundamentals.name)
            .where(
                StockFundamentals.sector == sector,
                StockFundamentals.symbol != symbol,
            )
        )
        for row in sec_result.all():
            if row.symbol not in gemini_validated and row.symbol not in industry_peers:
                industry_peers[row.symbol] = row.name or row.symbol

    # ── Step 4: Merge + Gemini ranking ──
    # Build candidate list: validated Gemini picks + industry scan results
    all_candidates: dict[str, str] = {}  # symbol → description for ranking

    # Load fundamentals for industry-scan peers so we have names + market cap
    if industry_peers:
        ip_result = await db.execute(
            select(StockFundamentals).where(
                StockFundamentals.symbol.in_(list(industry_peers.keys()))
            )
        )
        for f in ip_result.scalars().all():
            existing[f.symbol] = f

    for sym, rationale in gemini_validated.items():
        f = existing.get(sym)
        if f:
            mcap_str = f" (₹{_fmt_cap(float(f.market_cap))})" if f.market_cap else ""
            desc = f"{f.name or sym}{mcap_str} — {f.industry or f.sector or 'unknown'}"
        else:
            desc = sym
        all_candidates[sym] = desc

    for sym, cname in industry_peers.items():
        if sym not in all_candidates:
            f = existing.get(sym)
            if f:
                mcap_str = f" (₹{_fmt_cap(float(f.market_cap))})" if f.market_cap else ""
                desc = f"{f.name or sym}{mcap_str} — {f.industry or f.sector or 'unknown'}"
            else:
                desc = f"{cname} — {industry or sector or 'unknown'}"
            all_candidates[sym] = desc

    if len(all_candidates) <= 8:
        # Small enough list — use all of them, no need for ranking call
        final_peers = []
        for sym in all_candidates:
            rationale = gemini_validated.get(sym, f"Same industry: {industry or sector}")
            final_peers.append({"symbol": sym, "rationale": rationale})
    else:
        # Too many candidates — ask Gemini to rank
        candidates_block = "\n".join(
            f"- {sym}: {desc}" for sym, desc in sorted(all_candidates.items())
        )
        rank_prompt = RANK_PROMPT.format(
            symbol=symbol,
            name=name,
            sector=sector,
            industry=industry or sector or "unknown",
            market_cap_display=_fmt_cap(market_cap),
            cap_category=_cap_category(market_cap),
            candidates_block=candidates_block,
        )

        rank_raw = await call_gemini_with_rotation(user.id, db, rank_prompt)
        rank_match = re.search(r"\{.*\}", rank_raw, re.DOTALL)

        if rank_match:
            rank_parsed = json.loads(rank_match.group())
            ranked = rank_parsed.get("peers", [])
            gemini_notes = rank_parsed.get("notes", gemini_notes)

            final_peers = []
            for p in ranked[:8]:
                sym = p["symbol"].upper().strip()
                if sym in all_candidates and sym != symbol:
                    final_peers.append({"symbol": sym, "rationale": p.get("rationale", "")})
        else:
            logger.warning("peer_discovery: %s — ranking call returned no JSON, using unranked", symbol)
            final_peers = []
            for sym in list(all_candidates.keys())[:8]:
                rationale = gemini_validated.get(sym, f"Same industry: {industry or sector}")
                final_peers.append({"symbol": sym, "rationale": rationale})

    # ── Step 5: Store bidirectionally ──
    # Forward rows carry Gemini's ranking (0 = closest peer); reverse rows
    # get rank=NULL because we don't know the other side's preference order.
    await db.execute(
        delete(StockPeer).where(StockPeer.symbol == symbol)
    )

    now_utc = datetime.now(timezone.utc)
    for idx, p in enumerate(final_peers):
        # Forward: symbol -> peer, ranked
        fwd = pg_insert(StockPeer).values(
            symbol=symbol, peer_symbol=p["symbol"],
            source="gemini", rationale=p["rationale"],
            rank=idx, generated_at=now_utc,
        ).on_conflict_do_update(
            constraint="uq_stock_peer",
            set_={
                "source": "gemini",
                "rationale": p["rationale"],
                "rank": idx,
                "generated_at": now_utc,
            },
        )
        await db.execute(fwd)
        # Reverse: peer -> symbol, no rank (other side hasn't ranked us)
        rev = pg_insert(StockPeer).values(
            symbol=p["symbol"], peer_symbol=symbol,
            source="gemini", rationale=p["rationale"],
            rank=None, generated_at=now_utc,
        ).on_conflict_do_update(
            constraint="uq_stock_peer",
            set_={
                "source": "gemini",
                "rationale": p["rationale"],
                "generated_at": now_utc,
                # Don't overwrite the other side's rank if it exists.
            },
        )
        await db.execute(rev)

    await db.commit()

    return {
        "symbol": symbol,
        "peers": final_peers,
        "skipped": skipped,
        "industry_scan_count": len(industry_peers),
        "notes": gemini_notes,
        "source": "gemini",
    }


async def get_stored_peers(symbol: str, db: AsyncSession) -> list[dict]:
    """Return peers in deterministic relevance order.

    Forward rows carry Gemini's rank (0 = closest). Reverse rows have
    rank=NULL and are appended after the ranked ones. Within each group,
    ties break alphabetically so the order is stable across calls.
    """
    symbol = symbol.upper().strip()

    fwd = select(
        StockPeer.peer_symbol.label("peer"),
        StockPeer.rationale,
        StockPeer.rank,
    ).where(StockPeer.symbol == symbol)

    rev = select(
        StockPeer.symbol.label("peer"),
        StockPeer.rationale,
        # Reverse rows: rank from the originator's row (if any).
        StockPeer.rank,
    ).where(StockPeer.peer_symbol == symbol)

    combined = union_all(fwd, rev).subquery()
    result = await db.execute(
        select(combined).order_by(
            combined.c.rank.asc().nullslast(),
            combined.c.peer.asc(),
        )
    )
    rows = result.all()

    seen: set[str] = set()
    out: list[dict] = []
    for row in rows:
        if row.peer not in seen:
            seen.add(row.peer)
            out.append({"symbol": row.peer, "rationale": row.rationale})
    return out


async def get_effective_peers(
    symbol: str, db: AsyncSession, *, target: int = 6,
) -> tuple[list[dict], str]:
    """Single source of truth for peer resolution. Falls back through three
    tiers — stored Gemini peers → same-industry stocks → same-sector stocks
    — so both `evaluate_peers` (dashboard verdict) and the peers API endpoint
    (detail-panel peer cards) produce the same companies.

    Returns (peers, source). `peers` is a list of dicts:
        {"symbol": str, "rationale": str | None, "source": "stored"|"industry"|"sector"}
    `source` is the top-level provenance label: "stored", "industry_fallback",
    "sector_fallback", "mixed", or "none".
    """
    symbol = symbol.upper().strip()

    stored = await get_stored_peers(symbol, db)
    out: list[dict] = [{**p, "source": "stored"} for p in stored]
    seen: set[str] = {symbol, *(p["symbol"].upper() for p in out)}

    if len(out) >= target:
        return out, "stored"

    # Need fundamentals to do industry/sector fallback
    sf_q = await db.execute(
        select(StockFundamentals).where(StockFundamentals.symbol == symbol)
    )
    sf = sf_q.scalar_one_or_none()
    if not sf or (not sf.industry and not sf.sector):
        return out, "stored" if out else "none"

    added_industry = added_sector = 0

    if sf.industry:
        ind_q = await db.execute(
            select(StockFundamentals.symbol, StockFundamentals.name)
            .where(
                StockFundamentals.industry == sf.industry,
                StockFundamentals.symbol != symbol,
                StockFundamentals.market_cap.isnot(None),
            )
            .order_by(StockFundamentals.market_cap.desc())
            .limit(target * 2)
        )
        for sym, name in ind_q.all():
            su = sym.upper()
            if su not in seen and len(out) < target:
                out.append({
                    "symbol": sym,
                    "rationale": f"Same industry: {sf.industry}",
                    "source": "industry",
                })
                seen.add(su)
                added_industry += 1

    if len(out) < target and sf.sector:
        sec_q = await db.execute(
            select(StockFundamentals.symbol, StockFundamentals.name)
            .where(
                StockFundamentals.sector == sf.sector,
                StockFundamentals.symbol != symbol,
                StockFundamentals.market_cap.isnot(None),
            )
            .order_by(StockFundamentals.market_cap.desc())
            .limit(target * 2)
        )
        for sym, name in sec_q.all():
            su = sym.upper()
            if su not in seen and len(out) < target:
                out.append({
                    "symbol": sym,
                    "rationale": f"Same sector: {sf.sector}",
                    "source": "sector",
                })
                seen.add(su)
                added_sector += 1

    if not out:
        return out, "none"
    if added_sector or added_industry:
        if stored:
            return out, "mixed"
        return out, "industry_fallback" if added_industry else "sector_fallback"
    return out, "stored"


async def is_peers_stale(
    symbol: str, db: AsyncSession, *, max_age_days: int = 90,
) -> tuple[bool, int | None]:
    """Returns (is_stale, age_days). Treats reverse-only rows as fresh
    because their generated_at reflects the originating regeneration."""
    symbol = symbol.upper().strip()
    row = (await db.execute(
        select(func.max(StockPeer.generated_at)).where(
            (StockPeer.symbol == symbol) | (StockPeer.peer_symbol == symbol)
        )
    )).scalar_one_or_none()
    if row is None:
        return True, None
    age = datetime.now(timezone.utc) - row
    return age >= timedelta(days=max_age_days), age.days


async def ensure_peers(
    symbol: str, db: AsyncSession, user_id: int,
    *, min_peers: int = 2,
) -> bool:
    """Generate peers for `symbol` if the stored set has fewer than
    `min_peers`. Returns True if peers exist after the call, False if
    we couldn't seed (no industry/sector, no admin user, or Gemini
    failed).

    Used by:
      - stock_card.refresh_stock_analysis (auto-seed in card analysis)
      - morning_pipeline (Step 5 prelude for refresh mode — Phase B1)
      - news_onboarding (Phase C1)
    """
    stored = await get_stored_peers(symbol, db)
    if len(stored) >= min_peers:
        return True

    fund = (await db.execute(
        select(StockFundamentals).where(StockFundamentals.symbol == symbol.upper())
    )).scalar_one_or_none()
    if not fund or not (fund.industry or fund.sector):
        return False

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        return False

    try:
        logger.info(f"ensure_peers: generating for {symbol} (stored={len(stored)})")
        await generate_peers(symbol.upper(), db, user)
        return True
    except Exception as e:
        logger.warning(f"ensure_peers: generation failed for {symbol}: {e}")
        return False
