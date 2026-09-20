"""Gemini-written "why is X moving today?" summary per index.

For each index: pull last 24 h of Google News headlines via the existing
`fetch_google_news_custom` helper, ask Gemini for a structured JSON
{direction, magnitude, one_liner, drivers[], what_to_watch}, and upsert
into `index_news_summary`. Cached ~1 hour; recomputed on-demand via the
refresh endpoint.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.ai.gemini_client import call_gemini_with_rotation
from app.ai.prompt_helpers import INDIAN_MACRO_CONTEXT, STRICT_JSON_BOUNDARY
from app.ai.credential_rotation import NoCredentialsConfiguredError, AllCredentialsExhaustedError
from app.db.session import async_session
from app.models.market import IndexNewsSummary, IndexQuoteCache
from app.models.user import User
from app.services.market.indices_registry import INDICES, IndexEntry, get_entry
from app.services.news_sentiment import fetch_google_news_custom

logger = logging.getLogger(__name__)


PROMPT_TEMPLATE = """You are a market analyst. Given recent headlines about {display_name}, explain briefly why this index is moving today.

Today's quote (for context):
- Last price: {ltp}
- Change: {change_pct}%
- Direction: {dir_hint}

Headlines (most recent first):
{headlines}

{macro_context}

Return a JSON object with this structure:
{{
  "data_quality": "rich" | "thin",
  "direction": "UP" | "DOWN" | "FLAT",
  "magnitude": "SHARP" | "MILD" | "FLAT",
  "one_liner": "one sentence that a trader can read in 3 seconds",
  "drivers": [
    {{"label": "short phrase naming the driver", "weight": "high" | "medium" | "low"}}
  ],
  "what_to_watch": "one sentence on the key near-term trigger"
}}

Rules:
- Set `data_quality` to "thin" when fewer than 3 headlines directly discuss {display_name} OR when no concrete drivers can be cited from the headlines. Otherwise "rich".
- `drivers` must have 2–4 items ordered by weight descending. Every driver label must be traceable to at least one headline above.
- If `data_quality` is "thin", `one_liner` must explicitly say so ("Limited fresh coverage today...") and `magnitude` must be "FLAT".
- Never fabricate drivers — when the headlines don't support a claim, set `data_quality` to "thin" and shorten the drivers list.

{json_boundary}
"""


def _parse_gemini_json(raw: str) -> dict | None:
    cleaned = (raw or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


async def _load_quote(slug: str) -> IndexQuoteCache | None:
    async with async_session() as session:
        result = await session.execute(
            select(IndexQuoteCache).where(IndexQuoteCache.slug == slug)
        )
        return result.scalar_one_or_none()


def _dir_hint(change_pct: float | None) -> str:
    if change_pct is None:
        return "unknown"
    if change_pct >= 0.15:
        return f"up {change_pct:.2f}%"
    if change_pct <= -0.15:
        return f"down {abs(change_pct):.2f}%"
    return "flat"


async def refresh_summary_for(
    entry: IndexEntry,
    user: User,
    db=None,
    model: str | None = None,
) -> dict:
    """Pull news → call Gemini → upsert cache. Returns serialized payload."""
    headlines = await fetch_google_news_custom(entry.search_query, days=1)
    if len(headlines) < 3:
        # Expand to 2 days if today is sparse (weekends, holidays)
        more = await fetch_google_news_custom(entry.search_query, days=2)
        existing_urls = {h.get("url") for h in headlines}
        for h in more:
            if h.get("url") not in existing_urls:
                headlines.append(h)

    headlines = headlines[:15]

    quote = await _load_quote(entry.slug)
    ltp = float(quote.ltp) if quote and quote.ltp is not None else None
    change_pct = float(quote.change_pct) if quote and quote.change_pct is not None else None

    now = datetime.now(tz=timezone.utc)

    # No headlines and no API key path — persist an informational row.
    headlines_text = "\n".join(
        f"- [{h.get('date') or '?'}] {h.get('title')} ({h.get('source') or '?'})"
        for h in headlines
    ) or "(no headlines found)"

    prompt = PROMPT_TEMPLATE.format(
        display_name=entry.display_name,
        ltp=f"{ltp:.2f}" if ltp is not None else "unknown",
        change_pct=f"{change_pct:+.2f}" if change_pct is not None else "?",
        dir_hint=_dir_hint(change_pct),
        headlines=headlines_text,
        macro_context=INDIAN_MACRO_CONTEXT,
        json_boundary=STRICT_JSON_BOUNDARY,
    )

    parsed: dict | None = None
    error_message: str | None = None

    if not headlines:
        error_message = "No recent news found for this index"
    else:
        try:
            raw = await call_gemini_with_rotation(user.id, db, prompt)
            parsed = _parse_gemini_json(raw)
            if not parsed:
                error_message = "Gemini returned non-JSON output"
        except (NoCredentialsConfiguredError, AllCredentialsExhaustedError) as e:
            error_message = str(e)
        except Exception as e:
            logger.warning("Gemini summary failed for %s: %s", entry.slug, e)
            error_message = f"Gemini call failed: {str(e)[:200]}"

    # data_quality is derived in `_to_api_payload` from news_count +
    # error_message so adding the field cost zero migrations. The model's
    # own data_quality verdict (when present) refines a "rich" derivation
    # down to "thin" if the model self-identified weak coverage.
    p = parsed or {}
    model_data_quality = p.get("data_quality")
    values = {
        "slug": entry.slug,
        "direction": p.get("direction"),
        "magnitude": p.get("magnitude"),
        "one_liner": p.get("one_liner"),
        "drivers": p.get("drivers"),
        "what_to_watch": p.get("what_to_watch"),
        "top_headlines": headlines,
        "news_count": len(headlines),
        "model_used": "credential-default" if parsed else None,
        "generated_at": now,
        "error_message": error_message,
    }

    async with async_session() as session:
        stmt = pg_insert(IndexNewsSummary).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["slug"],
            set_={k: stmt.excluded[k] for k in values if k != "slug"},
        )
        await session.execute(stmt)
        await session.commit()

    return _to_api_payload(entry, values, model_data_quality=model_data_quality)


def _derive_data_quality(news_count: int | None, error_message: str | None, model_hint: str | None) -> str:
    """`thin` when news_count < 3 OR an error occurred OR the model
    self-flagged the result as thin. Otherwise `rich`. Front-end suppresses
    the drawer body on `thin` rather than showing a confident hallucination.
    """
    if (news_count or 0) < 3:
        return "thin"
    if error_message:
        return "thin"
    if (model_hint or "").lower() == "thin":
        return "thin"
    return "rich"


def _to_api_payload(
    entry: IndexEntry,
    row: IndexNewsSummary | dict,
    *,
    model_data_quality: str | None = None,
) -> dict:
    if isinstance(row, IndexNewsSummary):
        d = {
            "direction": row.direction,
            "magnitude": row.magnitude,
            "one_liner": row.one_liner,
            "drivers": row.drivers,
            "what_to_watch": row.what_to_watch,
            "top_headlines": row.top_headlines,
            "news_count": row.news_count,
            "model_used": row.model_used,
            "generated_at": row.generated_at.isoformat() if row.generated_at else None,
            "error_message": row.error_message,
        }
    else:
        d = {
            "direction": row.get("direction"),
            "magnitude": row.get("magnitude"),
            "one_liner": row.get("one_liner"),
            "drivers": row.get("drivers"),
            "what_to_watch": row.get("what_to_watch"),
            "top_headlines": row.get("top_headlines"),
            "news_count": row.get("news_count"),
            "model_used": row.get("model_used"),
            "generated_at": row["generated_at"].isoformat() if row.get("generated_at") else None,
            "error_message": row.get("error_message"),
        }
    d["slug"] = entry.slug
    d["display_name"] = entry.display_name
    d["data_quality"] = _derive_data_quality(
        d.get("news_count"), d.get("error_message"), model_data_quality
    )
    return d


async def read_cached_summary(slug: str) -> dict | None:
    entry = get_entry(slug)
    if not entry:
        return None
    async with async_session() as session:
        result = await session.execute(
            select(IndexNewsSummary).where(IndexNewsSummary.slug == slug)
        )
        row = result.scalar_one_or_none()
    if not row:
        return None
    return _to_api_payload(entry, row)
