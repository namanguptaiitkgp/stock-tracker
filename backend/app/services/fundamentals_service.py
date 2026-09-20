import asyncio
import logging
from datetime import datetime, timedelta, timezone

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import attributes

from app.models.fundamentals import StockFundamentals
from app.models.smart_money import ShareholdingPattern
from app.services.fundamentals_validation import clamp_fundamentals
from app.services.screener_fetcher import fetch_fundamentals as screener_fetch
from app.services.screener_presets import normalize_sector

logger = logging.getLogger(__name__)
FRESHNESS_HOURS = 24
# Pipelines refresh fundamentals weekly — quarterly filings don't move daily.
# Per-symbol user-initiated calls keep the 24h baseline.
FRESHNESS_HOURS_AUTO = 168
KEY_FIELDS = ["debt_to_equity", "roe", "revenue_growth_1y", "eps_growth_1y", "net_profit_margin", "forward_pe", "promoter_holding"]
MAX_CONCURRENT_YFINANCE = 10
# Corp-ann types that justify forcing a fundamentals refresh regardless of age.
MATERIAL_ANNOUNCEMENT_TYPES = ("Results", "Buy-back", "Dividend", "Pledge", "Bonus", "Split")

_SCREENER_TO_MODEL = {
    "market_cap": "market_cap",
    "pe_ratio": "pe_ratio",
    "roe": "roe",
    "dividend_yield": "dividend_yield",
    "debt_to_equity": "debt_to_equity",
    "revenue_growth_1y": "revenue_growth_1y",
    "eps_growth_1y": "eps_growth_1y",
    "net_profit_margin": "net_profit_margin",
    "promoter_holding": "promoter_holding",
    "shareholding_history": "shareholding_history",
    # Sector taxonomy — Screener.in gives Indian-market sectors that are
    # far more accurate than yfinance's US-taxonomy guesses. Sector is the
    # broad canonical bucket; industry is the fine-grained label.
    "sector": "sector",
    "industry": "industry",
}


def _safe_float(val) -> float | None:
    try:
        if val is None:
            return None
        f = float(val)
        if f != f or f == float("inf") or f == float("-inf"):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _yf_ticker(symbol: str, exchange: str = "NSE") -> str:
    suffix = ".NS" if exchange == "NSE" else ".BO"
    return f"{symbol}{suffix}"


def _fetch_from_yfinance(symbol: str, exchange: str = "NSE") -> dict:
    ticker = yf.Ticker(_yf_ticker(symbol, exchange))
    try:
        info = ticker.info or {}
    except Exception:
        info = {}

    if not info or info.get("trailingPE") is None and info.get("regularMarketPrice") is None:
        return {}

    # yfinance returns marketCap in raw rupees; we store crores (Screener's unit).
    market_cap_inr = _safe_float(info.get("marketCap"))
    market_cap_cr = market_cap_inr / 1e7 if market_cap_inr is not None else None

    return {
        "name": info.get("longName") or info.get("shortName"),
        # yfinance returns US/GICS-style sector names ("Consumer Cyclical",
        # "Industrial Goods", etc.); normalize to the 11 canonical Indian
        # buckets so downstream lookups (SectorAnalysis, screener_presets)
        # don't fragment.
        "sector": normalize_sector(info.get("sector")),
        "industry": info.get("industry"),
        "cmp": _safe_float(info.get("currentPrice") or info.get("regularMarketPrice")),
        "market_cap": market_cap_cr,
        "pe_ratio": _safe_float(info.get("trailingPE")),
        "ttm_pe": _safe_float(info.get("trailingPE")),
        "forward_pe": _safe_float(info.get("forwardPE")),
        "pb_ratio": _safe_float(info.get("priceToBook")),
        "revenue_growth_1y": _safe_float(info.get("revenueGrowth")),
        "eps_growth_1y": _safe_float(info.get("earningsGrowth")),
        "earnings_growth_forward": _safe_float(info.get("earningsQuarterlyGrowth")),
        "net_profit_margin": _safe_float(info.get("profitMargins")),
        # yfinance's debtToEquity is expressed as a percentage (150 = 1.5x).
        # Clamp impossibly large values to None — when shareholder equity is
        # near-zero or negative the ratio explodes (e.g. 26,650), and that
        # nonsense ends up in AI-generated risk alerts ("D/E of 266.5x").
        # Real-world D/E rarely exceeds 10x; treat anything past 50x as a
        # data anomaly and store null instead.
        "debt_to_equity": (lambda v: None if v is None or abs(v / 100) > 50 else v / 100)(
            _safe_float(info.get("debtToEquity"))
        ),
        "dividend_yield": _safe_float(info.get("dividendYield")),
        "roe": _safe_float(info.get("returnOnEquity")),
    }


async def get_fundamentals(
    symbol: str,
    db: AsyncSession,
    exchange: str = "NSE",
    force_refresh: bool = False,
    user_id: int | None = None,
) -> StockFundamentals | None:
    symbol = symbol.upper().strip()

    result = await db.execute(
        select(StockFundamentals).where(StockFundamentals.symbol == symbol)
    )
    existing = result.scalar_one_or_none()

    need_refresh = force_refresh or not existing or not existing.fetched_at
    if existing and existing.fetched_at and not force_refresh:
        age = datetime.now(timezone.utc) - existing.fetched_at
        if age >= timedelta(hours=FRESHNESS_HOURS):
            need_refresh = True

    record = existing
    sources: dict[str, str] = dict(existing.data_sources or {}) if existing else {}

    if need_refresh:
        # ── Step 1: Screener.in (primary) ────────────────────────────
        sc_data = await screener_fetch(symbol)
        if sc_data:
            # Translate Screener keys → model keys, then clamp out-of-range
            # values before they reach the DB. See fundamentals_validation.py.
            sc_clamped = clamp_fundamentals(
                {model_key: sc_data.get(sc_key) for sc_key, model_key in _SCREENER_TO_MODEL.items()},
                source="screener",
            )
            if existing:
                for model_key, val in sc_clamped.items():
                    if val is not None:
                        setattr(existing, model_key, val)
                        sources[model_key] = "screener"
                record = existing
            else:
                init = {k: v for k, v in sc_clamped.items() if v is not None}
                record = StockFundamentals(
                    symbol=symbol, exchange=exchange, **init,
                )
                for k in init:
                    sources[k] = "screener"
                db.add(record)

        # ── Step 2: yfinance (fills gaps only) ───────────────────────
        yf_data = _fetch_from_yfinance(symbol, exchange)
        if yf_data:
            yf_data = clamp_fundamentals(yf_data, source="yfinance")
            if record:
                for key, value in yf_data.items():
                    if value is not None and getattr(record, key, None) is None:
                        setattr(record, key, value)
                        sources[key] = "yfinance"
            else:
                record = StockFundamentals(
                    symbol=symbol, exchange=exchange, **{k: v for k, v in yf_data.items() if v is not None},
                )
                for k, v in yf_data.items():
                    if v is not None:
                        sources[k] = "yfinance"
                db.add(record)

        if record:
            record.fetched_at = datetime.now(timezone.utc)
            record.data_sources = sources
            attributes.flag_modified(record, "data_sources")
            await db.commit()
            await db.refresh(record)

    if not record:
        return None

    # ── Step 3: NSE ownership (promoter_holding + shareholding_history) ──
    need_ownership = getattr(record, "promoter_holding", None) is None
    need_sh_history = not record.shareholding_history
    if need_ownership or need_sh_history:
        try:
            sp_result = await db.execute(
                select(ShareholdingPattern)
                .where(ShareholdingPattern.symbol == symbol)
                .order_by(ShareholdingPattern.quarter_end_date.desc())
                .limit(8)
            )
            sp_rows = sp_result.scalars().all()
            if sp_rows:
                latest = sp_rows[0]
                if need_ownership and latest.promoter_pct is not None:
                    record.promoter_holding = float(latest.promoter_pct)
                    sources["promoter_holding"] = "nse_ownership"
                if need_sh_history:
                    history = []
                    for sp in sp_rows:
                        entry = {
                            "q": sp.quarter or (sp.quarter_end_date.strftime("%b %Y") if sp.quarter_end_date else None),
                            "promoter": float(sp.promoter_pct) if sp.promoter_pct is not None else None,
                            "mf": float(sp.mf_pct) if sp.mf_pct is not None else None,
                            "fii": float(sp.fii_pct) if sp.fii_pct is not None else None,
                            "dii": float(sp.dii_pct) if sp.dii_pct is not None else None,
                            "retail": float(sp.public_pct) if sp.public_pct is not None else None,
                            "pledge": float(sp.promoter_pledge_pct) if sp.promoter_pledge_pct is not None else None,
                        }
                        history.append(entry)
                    if history:
                        record.shareholding_history = history
                        sources["shareholding_history"] = "nse_ownership"
                        attributes.flag_modified(record, "shareholding_history")
                record.data_sources = sources
                attributes.flag_modified(record, "data_sources")
                await db.commit()
                await db.refresh(record)
        except Exception as e:
            logger.warning("ShareholdingPattern lookup failed for %s: %s", symbol, e)

    # ── Step 4: Gemini AI gap-fill ───────────────────────────────────
    _GEMINI_FIELDS = [
        "debt_to_equity", "roe", "revenue_growth_1y", "eps_growth_1y",
        "net_profit_margin", "forward_pe", "promoter_holding",
        "pe_ratio", "pb_ratio", "dividend_yield", "market_cap",
        "earnings_growth_forward", "high_52w", "low_52w",
    ]
    still_null = [f for f in _GEMINI_FIELDS if getattr(record, f, None) is None]
    if still_null and user_id is not None:
        try:
            ai_data = await _fill_gaps_with_gemini(symbol, still_null, user_id, db)
            if ai_data:
                ai_data = clamp_fundamentals(ai_data, source="gemini")
                filled = []
                for field in still_null:
                    if field in ai_data and ai_data[field] is not None:
                        setattr(record, field, ai_data[field])
                        sources[field] = "gemini"
                        filled.append(field)
                if filled:
                    record.data_sources = sources
                    attributes.flag_modified(record, "data_sources")
                    await db.commit()
                    await db.refresh(record)
                    logger.info("Gemini filled %d fields for %s: %s", len(filled), symbol, filled)
        except Exception as e:
            logger.warning("Gemini fallback failed for %s: %s", symbol, e)

    return record


async def _fill_gaps_with_gemini(symbol: str, null_fields: list[str], user_id: int, db) -> dict:
    """Ask Gemini AI for fundamental data as last resort."""
    from app.ai.gemini_client import call_gemini_with_rotation

    field_labels = {
        "debt_to_equity": "Debt to Equity ratio (number, e.g. 0.5)",
        "roe": "Return on Equity (decimal, e.g. 0.15 for 15%)",
        "revenue_growth_1y": "Revenue Growth 1 Year (decimal, e.g. 0.12 for 12%)",
        "eps_growth_1y": "EPS Growth 1 Year (decimal, e.g. 0.10 for 10%)",
        "net_profit_margin": "Net Profit Margin (decimal, e.g. 0.08 for 8%)",
        "forward_pe": "Forward P/E ratio (number, e.g. 20.5)",
        "promoter_holding": "Promoter Holding percentage (number, e.g. 47.2 for 47.2%)",
        "pe_ratio": "Trailing P/E ratio (number, e.g. 22.5)",
        "pb_ratio": "Price to Book ratio (number, e.g. 3.2)",
        "dividend_yield": "Dividend Yield (decimal, e.g. 0.012 for 1.2%)",
        "market_cap": "Market Capitalization in Crores (number, e.g. 1500000)",
        "earnings_growth_forward": "Forward Earnings Growth (decimal, e.g. 0.15 for 15%)",
        "high_52w": "52-Week High price in Rupees (number, e.g. 3217.0)",
        "low_52w": "52-Week Low price in Rupees (number, e.g. 2220.0)",
    }

    fields_needed = [f"{field_labels.get(f, f)}" for f in null_fields if f in field_labels]
    if not fields_needed:
        return {}

    import json
    prompt = f"""For the Indian stock {symbol} listed on NSE, provide these financial metrics.
Return a JSON object with these exact keys. Use null for any value you are not confident about.
All percentage values should be decimals (e.g., 15% = 0.15). Debt/Equity and P/E are plain numbers.

Needed: {json.dumps({f: field_labels.get(f, f) for f in null_fields if f in field_labels})}

COST FAIL-SAFE: If you cannot confidently find at least 3 of the requested
values from authoritative Indian financial sources (NSE filings, BSE
announcements, company annual reports, Screener.in, MoneyControl), return
an empty JSON object `{{}}` with no explanation. Do NOT fabricate values
you are uncertain about — partial unreliable data costs us more than
returning nothing.

Start your response with "{{" and end with "}}". Do not output markdown
fences or any prose before or after the JSON."""

    try:
        raw = await call_gemini_with_rotation(user_id, db, prompt, tools=[{"googleSearch": {}}])
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
        data = json.loads(cleaned)
        result = {}
        for field in null_fields:
            if field in data and data[field] is not None:
                val = _safe_float(data[field])
                if val is not None:
                    result[field] = val
        return result
    except Exception as e:
        logger.warning(f"Gemini fundamentals failed for {symbol}: {e}")
        return {}


async def get_fundamentals_bulk(
    symbols: list[str],
    db: AsyncSession,
    exchange: str = "NSE",
    user_id: int | None = None,
) -> dict[str, StockFundamentals]:
    out: dict[str, StockFundamentals] = {}
    for symbol in symbols:
        record = await get_fundamentals(symbol, db, exchange=exchange, user_id=user_id)
        if record:
            out[symbol.upper()] = record
    return out


async def get_cached_fundamentals_bulk(
    symbols: list[str],
    db: AsyncSession,
) -> dict[str, StockFundamentals]:
    """Fast: only reads from DB, no yfinance calls. Use for instant page loads."""
    if not symbols:
        return {}
    upper_syms = [s.upper().strip() for s in symbols]
    result = await db.execute(
        select(StockFundamentals).where(StockFundamentals.symbol.in_(upper_syms))
    )
    return {f.symbol: f for f in result.scalars().all()}


def _fetch_sync(symbol: str, exchange: str) -> tuple[str, dict]:
    """Blocking yfinance call — run via asyncio.to_thread."""
    try:
        return symbol, _fetch_from_yfinance(symbol, exchange)
    except Exception as e:
        logger.warning(f"yfinance fetch failed for {symbol}: {e}")
        return symbol, {}


async def _symbols_with_recent_material_announcement(
    db: AsyncSession, symbols: list[str], days: int = 7,
) -> set[str]:
    """Subset of `symbols` that have a material corporate announcement in the
    last `days`. Materiality is restricted to result/buyback/dividend/pledge
    types — see MATERIAL_ANNOUNCEMENT_TYPES."""
    if not symbols:
        return set()
    from sqlalchemy import text
    try:
        rows = await db.execute(
            text(
                "SELECT DISTINCT symbol FROM corporate_announcements "
                "WHERE symbol = ANY(:syms) "
                "  AND announcement_type = ANY(:types) "
                "  AND announcement_date >= (CURRENT_DATE - (:days || ' days')::interval)"
            ),
            {"syms": symbols, "types": list(MATERIAL_ANNOUNCEMENT_TYPES), "days": str(days)},
        )
        return {row.symbol for row in rows}
    except Exception as e:
        # If the table isn't there yet, or the query fails, just don't
        # force-refresh — the time-based gate still applies.
        logger.debug("Material announcement lookup failed: %s", e)
        return set()


async def refresh_fundamentals_bulk(
    symbols: list[str],
    db: AsyncSession,
    exchange: str = "NSE",
    only_stale: bool = True,
    freshness_hours: int = FRESHNESS_HOURS,
) -> dict:
    """Parallel yfinance fetches for many symbols at once. Updates DB cache.
    Returns counts: {fetched, skipped, failed}.

    `freshness_hours` lets pipelines pass FRESHNESS_HOURS_AUTO (168 = 7 days)
    for cheap weekly refresh, while user-initiated paths keep the 24h default.
    Symbols with a material corporate announcement in the last 7 days are
    force-fetched regardless of age."""
    if not symbols:
        return {"fetched": 0, "skipped": 0, "failed": 0}

    upper_syms = [s.upper().strip() for s in symbols if s.strip()]

    # Figure out which need refreshing
    existing = await get_cached_fundamentals_bulk(upper_syms, db)
    event_force = await _symbols_with_recent_material_announcement(db, upper_syms)
    now = datetime.now(timezone.utc)
    to_fetch: list[str] = []
    skipped = 0

    for sym in upper_syms:
        cached = existing.get(sym)
        if sym in event_force:
            # Material corp action — refresh even if recently fetched.
            to_fetch.append(sym)
            continue
        if only_stale and cached and cached.fetched_at:
            age = now - cached.fetched_at
            if age < timedelta(hours=freshness_hours):
                skipped += 1
                continue
        to_fetch.append(sym)

    if not to_fetch:
        return {"fetched": 0, "skipped": skipped, "failed": 0}

    # Parallel fetches with concurrency limit
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_YFINANCE)

    async def fetch_one(sym: str):
        async with semaphore:
            return await asyncio.to_thread(_fetch_sync, sym, exchange)

    results = await asyncio.gather(*[fetch_one(s) for s in to_fetch], return_exceptions=True)

    fetched = 0
    failed = 0
    for result in results:
        if isinstance(result, Exception):
            failed += 1
            continue
        sym, data = result
        if not data:
            failed += 1
            continue

        data = clamp_fundamentals(data, source="yfinance_bulk")

        existing_rec = existing.get(sym)
        if existing_rec:
            for key, value in data.items():
                if value is not None:
                    setattr(existing_rec, key, value)
            existing_rec.fetched_at = now
        else:
            db.add(StockFundamentals(
                symbol=sym,
                exchange=exchange,
                fetched_at=now,
                **data,
            ))
        fetched += 1

    await db.commit()
    return {"fetched": fetched, "skipped": skipped, "failed": failed}


def serialize(f: StockFundamentals) -> dict:
    return {
        "symbol": f.symbol,
        "exchange": f.exchange,
        "name": f.name,
        "sector": f.sector,
        "industry": f.industry,
        "cmp": float(f.cmp) if f.cmp is not None else None,
        "market_cap": float(f.market_cap) if f.market_cap is not None else None,
        "pe_ratio": float(f.pe_ratio) if f.pe_ratio is not None else None,
        "ttm_pe": float(f.ttm_pe) if f.ttm_pe is not None else None,
        "forward_pe": float(f.forward_pe) if f.forward_pe is not None else None,
        "pb_ratio": float(f.pb_ratio) if f.pb_ratio is not None else None,
        "revenue_growth_1y": float(f.revenue_growth_1y) if f.revenue_growth_1y is not None else None,
        "eps_growth_1y": float(f.eps_growth_1y) if f.eps_growth_1y is not None else None,
        "earnings_growth_forward": float(f.earnings_growth_forward) if f.earnings_growth_forward is not None else None,
        "net_profit_margin": float(f.net_profit_margin) if f.net_profit_margin is not None else None,
        "debt_to_equity": float(f.debt_to_equity) if f.debt_to_equity is not None else None,
        "dividend_yield": float(f.dividend_yield) if f.dividend_yield is not None else None,
        "roe": float(f.roe) if f.roe is not None else None,
        "promoter_holding": float(f.promoter_holding) if f.promoter_holding is not None else None,
        "shareholding_history": f.shareholding_history if f.shareholding_history else None,
        "high_52w": float(f.high_52w) if f.high_52w is not None else None,
        "low_52w": float(f.low_52w) if f.low_52w is not None else None,
        "data_sources": f.data_sources if f.data_sources else {},
        "fetched_at": f.fetched_at.isoformat() if f.fetched_at else None,
    }
