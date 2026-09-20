"""Batch-classify news headlines via Gemini.

For each headline returns:
  - stocks (list of {symbol, name}) — companies mentioned
  - sentiment ("tailwind" | "headwind" | "context")
  - confidence ("high" | "medium" | "low")

Tailwind = clearly positive for the stock(s); headwind = clearly negative;
context = macro/sector/policy with no specific directional implication.

Two-layer cache: fast in-memory dict (L1, per-worker, 1h) backed by
DB-persistent cache (L2, shared across workers, 6h) via data_cache.
Only headlines missing from both layers go to Gemini.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time

from app.ai.gemini_client import call_gemini_with_rotation
from app.ai.credential_rotation import NoCredentialsConfiguredError, AllCredentialsExhaustedError

logger = logging.getLogger(__name__)

CACHE_SECONDS = 60 * 60  # 1 hour — L1 in-memory TTL
DB_CACHE_SECONDS = 6 * 60 * 60  # 6 hours — L2 DB TTL (headlines don't change)
_cache: dict[str, tuple[float, dict]] = {}

PROMPT_TEMPLATE = """You are a financial news analyst. For each headline below, identify:
1. Which NSE/BSE-listed Indian companies are mentioned (use exact NSE trading symbol).
2. [NOISE FILTER] If a headline is macro/sector/policy news with no specific listed-company focus
   (e.g. RBI policy review, broad FII flow data, inflation print, generic sector commentary),
   completely OMIT it from your response array. Do NOT return an object for it.
   Only return objects for headlines that explicitly mention one or more listed Indian companies.
3. For the headlines you keep, classify directional sentiment for the named companies:
   - "tailwind" — clearly positive (earnings beat, big order, regulatory tailwind, upgrades)
   - "headwind" — clearly negative (earnings miss, downgrades, fines, deferred orders, lawsuits)
   - "neutral"  — listed company mentioned but no clear directional read

Output ONLY a JSON array, no prose, no markdown fences. ONE OBJECT ONLY for headlines you kept
(macro headlines must be absent — the array length will be smaller than the input length):

[
  {{
    "headline": "<exact original title>",
    "stocks": [{{"symbol": "HDFCBANK", "name": "HDFC Bank"}}],
    "sentiment": "tailwind" | "headwind" | "neutral",
    "confidence": "high" | "medium" | "low"
  }}
]

Rules:
- Use the NSE trading symbol (RELIANCE, TCS, HDFCBANK, INFY, etc.) — NOT BSE codes.
- For banking: HDFCBANK, ICICIBANK, SBIN, KOTAKBANK, AXISBANK, INDUSINDBK, BANDHANBNK, IDFCFIRSTB, etc.
- For IT: TCS, INFY, WIPRO, HCLTECH, TECHM, LTIM, PERSISTENT, MPHASIS, COFORGE.
- A headline can mention multiple companies — include all.
- [SUBSIDIARY → PARENT] When a headline names an unlisted subsidiary or product, you MUST tag the
  listed parent's NSE symbol. ALWAYS, not "if obvious". Common Indian-market mappings:
    * "Bharti Life", "Airtel", "Bharti Telecom" → BHARTIARTL
    * "ICICI Pru Life", "ICICI Prudential Life", "ICICI Lombard" → ICICIPRULI / ICICIGI
    * "HDFC Life", "HDFC ERGO", "HDFC AMC" → HDFCLIFE / HDFCAMC
    * "SBI Life", "SBI Cards", "SBI Funds" → SBILIFE / SBICARD
    * "Reliance Jio", "JioMart", "Reliance Retail", "Network18" → RELIANCE
    * "Tata Capital", "Tata Digital", "BigBasket" → relevant listed Tata entity (TATAINVEST/TITAN/etc.)
    * "Blinkit", "Hyperpure" → ETERNAL (formerly Zomato)
    * "Adani Green Hydrogen", "ATGL" → relevant listed Adani entity (ADANIGREEN/ADANIENT/etc.)
    * "L&T Finance", "Mindtree" → LTF / LTIM
    * "Mahindra Holidays", "M&M Financial" → MHRIL / M&MFIN
- [M&A on subsidiaries] When a foreign or strategic acquirer buys/sells a stake in a listed-company
  subsidiary, tag BOTH the listed parent AND any directly-listed sister entity affected. Worked
  example: "Prudential to buy 75% of Bharti Life, cut ICICI Pru Life holding to 10%" →
  stocks = [{{"symbol": "BHARTIARTL", "name": "Bharti Airtel"}}, {{"symbol": "ICICIPRULI", "name": "ICICI Prudential Life"}}].
  Missing the listed parent on M&A involving its subsidiary is the worst possible miss — never do this.
- "stocks" must always be non-empty for headlines you keep — if you can't identify a specific company,
  omit the headline entirely (noise filter).

Headlines (one per line, prefixed with index):
{headlines}

Start your response with "[" and end with "]". Do not output markdown fences or any prose before or after the JSON.
"""


def _hash_title(t: str) -> str:
    return hashlib.sha1(t.encode("utf-8")).hexdigest()[:16]


def _strip_fences(raw: str) -> str:
    s = (raw or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1].rsplit("```", 1)[0]
    return s.strip()


async def _db_cache_get_bulk(hashes: list[str]) -> dict[str, dict]:
    """Fetch multiple classification results from DB cache in one query."""
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.db.session import async_session
    from app.models.fetch_cache import FetchCache

    keys = [f"classify:{h}" for h in hashes]
    now = datetime.now(tz=timezone.utc)
    results: dict[str, dict] = {}
    try:
        async with async_session() as session:
            rows = await session.execute(
                select(FetchCache).where(
                    FetchCache.cache_key.in_(keys),
                    FetchCache.expires_at >= now,
                )
            )
            for row in rows.scalars():
                h = row.cache_key.removeprefix("classify:")
                results[h] = row.payload
    except Exception as e:
        logger.warning(f"classify: DB cache bulk read failed: {e}")
    return results


async def _db_cache_set_bulk(entries: dict[str, dict]) -> None:
    """Persist multiple classification results to DB cache in one transaction."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.db.session import async_session
    from app.models.fetch_cache import FetchCache

    now = datetime.now(tz=timezone.utc)
    expires = now + timedelta(seconds=DB_CACHE_SECONDS)
    try:
        async with async_session() as session:
            for h, result in entries.items():
                stmt = pg_insert(FetchCache).values(
                    cache_key=f"classify:{h}",
                    source="classify",
                    payload=result,
                    fetched_at=now,
                    expires_at=expires,
                    refresh_count=0,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["cache_key"],
                    set_={
                        "payload": stmt.excluded.payload,
                        "fetched_at": stmt.excluded.fetched_at,
                        "expires_at": stmt.excluded.expires_at,
                        "refresh_count": FetchCache.refresh_count + 1,
                    },
                )
                await session.execute(stmt)
            await session.commit()
    except Exception as e:
        logger.warning(f"classify: DB cache bulk write failed: {e}")


async def classify_headlines(items: list[dict], user_id: int, db) -> list[dict]:
    """Annotate each item dict with `stocks`, `sentiment`, `confidence`.

    Items already containing `stocks` (e.g. BSE filings) keep their stocks but
    still get a sentiment/confidence assignment.

    Returns the SAME list with extra keys merged in.
    """
    if not items:
        return items

    # L1: check in-memory cache
    titles_needing_l2: list[str] = []
    out_results: dict[str, dict] = {}
    now = time.time()
    for it in items:
        title = it["title"]
        h = _hash_title(title)
        cached = _cache.get(h)
        if cached and (now - cached[0] < CACHE_SECONDS):
            out_results[title] = cached[1]
            continue
        if title not in out_results:
            titles_needing_l2.append(title)

    # L2: check DB cache for L1 misses
    titles_to_classify: list[str] = []
    if titles_needing_l2:
        l2_hashes = {_hash_title(t): t for t in titles_needing_l2}
        db_hits = await _db_cache_get_bulk(list(l2_hashes.keys()))
        for h, result in db_hits.items():
            title = l2_hashes[h]
            out_results[title] = result
            _cache[h] = (now, result)
        for h, title in l2_hashes.items():
            if title not in out_results:
                titles_to_classify.append(title)

    l1_hits = len(items) - len(titles_needing_l2)
    l2_hits = len(titles_needing_l2) - len(titles_to_classify)
    if titles_needing_l2:
        logger.info(
            f"classify: {len(items)} items — {l1_hits} L1 hits, {l2_hits} L2 hits, "
            f"{len(titles_to_classify)} need Gemini"
        )

    # L3: call Gemini for remaining misses
    db_to_persist: dict[str, dict] = {}
    if titles_to_classify:
        batch_size = 40
        for batch_start in range(0, len(titles_to_classify), batch_size):
            batch = titles_to_classify[batch_start : batch_start + batch_size]
            prompt = PROMPT_TEMPLATE.format(
                headlines="\n".join(f"{i+1}. {t}" for i, t in enumerate(batch))
            )
            try:
                raw = await call_gemini_with_rotation(user_id, db, prompt)
                parsed = json.loads(_strip_fences(raw))
                if not isinstance(parsed, list):
                    raise ValueError("expected a JSON array")

                # Match returned entries to input titles by NORMALISED title text
                # (case-/whitespace-insensitive). The new noise-filter prompt
                # OMITS macro headlines from the response — index-based mapping
                # against `batch` would silently misalign. Title-keyed lookup
                # tolerates that. Headlines that we sent but the model did NOT
                # return are treated as "noise filtered" and cached as such so
                # the same macro headlines don't churn tokens every cycle.
                def _norm(s: str | None) -> str:
                    return (s or "").strip().lower()

                norm_to_input = {_norm(t): t for t in batch}
                matched_titles: set[str] = set()
                for entry in parsed:
                    if not isinstance(entry, dict):
                        continue
                    input_title = norm_to_input.get(_norm(entry.get("headline")))
                    if not input_title:
                        continue  # hallucinated headline not in our batch — drop
                    matched_titles.add(input_title)
                    result = {
                        "stocks": entry.get("stocks") or [],
                        "sentiment": entry.get("sentiment") or "neutral",
                        "confidence": entry.get("confidence") or "low",
                    }
                    out_results[input_title] = result
                    h = _hash_title(input_title)
                    _cache[h] = (now, result)
                    db_to_persist[h] = result

                # Anything the model omitted = noise. Cache as "context" with
                # high confidence so re-runs skip these via L1/L2 cache hits.
                # Without this synthetic write, every macro headline triggers
                # cache-miss + re-classify-and-re-omit every cycle, defeating
                # the entire point of the noise-filter rule.
                for title in batch:
                    if title in matched_titles:
                        continue
                    synthetic = {
                        "stocks": [],
                        "sentiment": "context",
                        "confidence": "high",
                    }
                    out_results[title] = synthetic
                    h = _hash_title(title)
                    _cache[h] = (now, synthetic)
                    db_to_persist[h] = synthetic
            except Exception as e:
                logger.warning(f"classify_headlines: Gemini batch failed (batch {batch_start // batch_size + 1}): {e}")
                for t in batch:
                    out_results[t] = {"stocks": [], "sentiment": "context", "confidence": "low"}

    if db_to_persist:
        await _db_cache_set_bulk(db_to_persist)

    # Merge back into items
    for it in items:
        result = out_results.get(it["title"], {"stocks": [], "sentiment": "context", "confidence": "low"})
        if not it.get("stocks"):
            it["stocks"] = result.get("stocks") or []
        it["sentiment"] = result.get("sentiment") or "context"
        it["confidence"] = result.get("confidence") or "low"
    return items


async def clear_cache() -> None:
    from app.services.data_cache import cache_invalidate_prefix
    _cache.clear()
    await cache_invalidate_prefix("classify:")
