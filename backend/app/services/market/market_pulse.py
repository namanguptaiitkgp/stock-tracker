"""Market Pulse — Gemini-generated narrative explaining the current market direction.

Combines:
- Smart trend snapshot (`compute_market_trend`)
- Multi-source news aggregation (`fetch_market_news`)
- Gemini analysis with a structured JSON output

Cached in `market_pulse` table with TTL (30 min by default).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, select

from app.ai.gemini_client import call_gemini_with_rotation
from app.ai.credential_rotation import NoCredentialsConfiguredError, AllCredentialsExhaustedError
from app.db.session import async_session
from app.models.market import MarketPulse
from app.models.user import User
from app.services.market.indices_quotes import fetch_and_cache_quotes, read_cached_quotes
from app.services.market.market_news_aggregator import fetch_market_news
from app.services.market.market_trend import compute_market_trend

logger = logging.getLogger(__name__)

PULSE_TTL_SECONDS = 30 * 60  # 30 minutes

PROMPT_TEMPLATE = """You are a market analyst. The Indian stock market direction snapshot:

Direction: {direction} ({magnitude}) — {label}
Weighted score: {score:+.2f}%
Breadth: {breadth_up}/{breadth_total} indices up
India VIX: {vix_summary}

Top index movers (positive change_pct = up):
{movers}

Recent market headlines (most recent first):
{headlines}

Return ONLY a JSON object with this structure — no prose, no markdown fences:
{{
  "one_liner": "one sentence (10-15 words) capturing why the market is {direction} today",
  "summary": "2-3 sentence narrative connecting the index moves to the news drivers",
  "drivers": [
    {{"label": "short phrase naming the driver", "weight": "high" | "medium" | "low", "sentiment": "positive" | "negative" | "neutral"}}
  ],
  "top_headlines": [
    {{"title": "<exact title from headlines above>", "source": "<source name>", "impact": "high" | "medium" | "low"}}
  ]
}}

Rules:
- `drivers` must have 3-5 items ordered by weight descending. Each must be traceable to at least one headline above.
- `top_headlines` must have 3-5 items selected from the most impactful headlines above (use exact titles).
- If headlines are too sparse, set `summary` to acknowledge that and keep drivers minimal.
- Use India-specific context: FII/DII flows, RBI, budget, crude, INR, banking, IT exports, etc.
- Be specific. Avoid generic phrases like "mixed sentiment" — say WHAT and WHY.
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


def _format_movers(components: list[dict], top_n: int = 6) -> str:
    if not components:
        return "(no index data available)"
    sorted_c = sorted(components, key=lambda c: abs(c.get("change_pct") or 0), reverse=True)
    lines = []
    for c in sorted_c[:top_n]:
        cp = c.get("change_pct")
        cp_str = f"{cp:+.2f}%" if cp is not None else "?"
        lines.append(f"- {c.get('name')}: {cp_str}")
    return "\n".join(lines)


def _format_headlines(headlines: list[dict], top_n: int = 30) -> str:
    if not headlines:
        return "(no headlines found)"
    lines = []
    for h in headlines[:top_n]:
        src = h.get("source") or "?"
        lines.append(f"- {h.get('title')} ({src})")
    return "\n".join(lines)


def _enrich_top_headlines_with_urls(
    parsed_top: list[dict] | None,
    raw_headlines: list[dict],
) -> list[dict]:
    """Gemini gets only titles + sources (no URLs) in the prompt, so it can't
    echo real URLs back. We ask it to "use exact titles", then look each
    title up in the raw scraper output here and copy over the real URL,
    source, and any other metadata. Without this, the dashboard's headline
    cards link to https://bullandbear.site/link (the LLM copying the prompt
    placeholder literally).

    Title matching uses normalized comparison (strip + casefold) so minor
    whitespace/case drift doesn't break the link. If no match found, the
    headline still renders but with url='' — the frontend's `h.url || "#"`
    fallback prevents a broken navigation.
    """
    if not parsed_top:
        return []

    def _norm(s: str | None) -> str:
        return (s or "").strip().casefold()

    by_title: dict[str, dict] = {_norm(h.get("title")): h for h in raw_headlines if h.get("title")}
    enriched: list[dict] = []
    for item in parsed_top:
        raw = by_title.get(_norm(item.get("title")))
        out = dict(item)
        # Trust the raw scraper for url + source — LLMs hallucinate URLs.
        out["url"] = (raw or {}).get("url") or (raw or {}).get("link") or ""
        if raw and raw.get("source"):
            out["source"] = raw["source"]
        enriched.append(out)
    return enriched


def _vix_summary(vix: dict | None) -> str:
    if not vix:
        return "n/a"
    ltp = vix.get("ltp")
    cp = vix.get("change_pct")
    return f"{ltp:.2f} ({cp:+.2f}%)" if ltp is not None and cp is not None else "n/a"


async def _ensure_quotes(user: User) -> list[dict]:
    """Read cached quotes; refresh if empty."""
    quotes = await read_cached_quotes()
    has_data = any(q.get("ltp") is not None for q in quotes)
    if not has_data:
        try:
            quotes = await fetch_and_cache_quotes(user)
        except Exception as e:
            logger.warning(f"failed to refresh quotes for pulse: {e}")
    return quotes


async def refresh_market_pulse(user: User, db=None, model: str | None = None) -> dict:
    """Compute trend + fetch news + call Gemini → persist + return payload."""
    quotes_task = _ensure_quotes(user)
    news_task = fetch_market_news(days=1, cap=50)
    quotes, headlines = await asyncio.gather(quotes_task, news_task)

    trend = compute_market_trend(quotes)

    now = datetime.now(tz=timezone.utc)
    expires = now + timedelta(seconds=PULSE_TTL_SECONDS)

    headlines_text = _format_headlines(headlines)
    movers_text = _format_movers(trend.get("components") or [])

    prompt = PROMPT_TEMPLATE.format(
        direction=trend.get("direction") or "flat",
        magnitude=trend.get("magnitude") or "neutral",
        label=trend.get("label") or "Mostly Flat",
        score=trend.get("adjusted_score") or 0.0,
        breadth_up=trend.get("breadth_up") or 0,
        breadth_total=trend.get("breadth_total") or 0,
        vix_summary=_vix_summary(trend.get("vix")),
        movers=movers_text,
        headlines=headlines_text,
    )

    parsed: dict | None = None
    error_message: str | None = None

    if not headlines:
        error_message = "No recent market news found"
    else:
        try:
            raw = await call_gemini_with_rotation(user.id, db, prompt)
            parsed = _parse_gemini_json(raw)
            if not parsed:
                error_message = "Gemini returned non-JSON output"
        except (NoCredentialsConfiguredError, AllCredentialsExhaustedError) as e:
            error_message = str(e)
        except Exception as e:
            logger.warning(f"market pulse Gemini call failed: {e}")
            error_message = f"Gemini call failed: {str(e)[:200]}"

    row = MarketPulse(
        direction=trend.get("direction"),
        magnitude=trend.get("magnitude"),
        label=trend.get("label"),
        score=trend.get("adjusted_score"),
        breadth=trend.get("breadth"),
        components=trend.get("components"),
        vix=trend.get("vix"),
        one_liner=(parsed or {}).get("one_liner"),
        summary=(parsed or {}).get("summary"),
        drivers=(parsed or {}).get("drivers"),
        # Gemini's top_headlines lack URLs (we don't pass them in). Enrich by
        # title-matching back to raw scraper output so the frontend gets real
        # clickable links. Fallback to raw headlines[:5] if Gemini failed.
        top_headlines=_enrich_top_headlines_with_urls(
            (parsed or {}).get("top_headlines"), headlines,
        ) or headlines[:5],
        news_count=len(headlines),
        model_used="credential-default" if parsed else None,
        generated_at=now,
        expires_at=expires,
        error_message=error_message,
    )

    async with async_session() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)

    return _to_payload(row, trend)


def _to_payload(row: MarketPulse, trend: dict | None = None) -> dict:
    return {
        "id": row.id,
        "direction": row.direction,
        "magnitude": row.magnitude,
        "label": row.label,
        "score": float(row.score) if row.score is not None else None,
        "breadth": float(row.breadth) if row.breadth is not None else None,
        "components": row.components,
        "vix": row.vix,
        "one_liner": row.one_liner,
        "summary": row.summary,
        "drivers": row.drivers,
        "top_headlines": row.top_headlines,
        "news_count": row.news_count,
        "model_used": row.model_used,
        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "error_message": row.error_message,
    }


async def read_latest_pulse() -> MarketPulse | None:
    async with async_session() as session:
        result = await session.execute(
            select(MarketPulse).order_by(desc(MarketPulse.generated_at)).limit(1)
        )
        return result.scalar_one_or_none()


async def get_or_refresh_pulse(user: User, db=None) -> dict:
    """Stale-while-revalidate: return the last pulse immediately if one
    exists, then refresh in the background when stale. Only block on the
    Gemini regeneration when there is no usable cache at all."""
    latest = await read_latest_pulse()
    now = datetime.now(tz=timezone.utc)

    fresh_enough = (
        latest is not None
        and latest.expires_at is not None
        and latest.expires_at > now
        and not latest.error_message
    )
    if fresh_enough:
        return {**_to_payload(latest), "cached": True}

    if latest and not latest.error_message:
        # Have something to show; refresh in the background so the user
        # doesn't wait 15-20s on Gemini.
        async def _bg() -> None:
            try:
                await refresh_market_pulse(user, db=db)
            except Exception as e:
                logger.warning(f"Background pulse refresh failed: {e}")

        asyncio.create_task(_bg())
        return {**_to_payload(latest), "cached": True, "stale": True}

    # No usable cache — must block.
    fresh = await refresh_market_pulse(user, db=db)
    return {**fresh, "cached": False}
