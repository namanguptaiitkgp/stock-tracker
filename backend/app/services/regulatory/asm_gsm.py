"""Daily fetch of NSE ASM (Additional Surveillance Measures) and
GSM (Graded Surveillance Mechanism) lists. Both are stock-level
regulatory flags that mandate sell discipline in the Smart Exit
prompt (`SELL_STRATEGY_PROMPT`).

NSE's Akamai layer blocks raw API requests — must hit the landing
page first to establish session cookies AND set a page-matched
`Referer` header on the API call itself. Verified live against
production NSE on 2026-05-17 in plan §G1.

Endpoint paths verified live:
- ASM: ``/api/reportASM`` returns ``{"longterm": {"data": [...]}, "shortterm": {"data": [...]}}``
- GSM: ``/api/reportGSM`` returns a flat list

Stage labels emitted by ``get_surveillance_flags()``:
- ``"LTASM Stage I/II/III/IV"`` — long-term ASM (most severe of the ASM tier)
- ``"STASM Stage I/II/III/IV"`` — short-term ASM
- ``"GSM"`` — graded surveillance (Roman-numeral internal counter on
  the response is dropped for v1; the flag presence alone drives the
  Smart Exit prompt's hard sell rule)

GSM overrides ASM when a symbol appears on both lists — GSM is the
more severe regime (T+T segment, eventual suspension).
"""

from __future__ import annotations

import logging
from datetime import date

import httpx

from app.services.data_cache import cache_get_or_fetch

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

ASM_LANDING = "https://www.nseindia.com/reports/asm"
GSM_LANDING = "https://www.nseindia.com/reports/gsm"
ASM_URL = "https://www.nseindia.com/api/reportASM"
GSM_URL = "https://www.nseindia.com/api/reportGSM"

# NSE refreshes ASM/GSM once daily after market close. A 24h TTL keeps
# the dashboard responsive while ensuring at most one fetch per session
# per worker; the celery beat job in app/tasks/regulatory.py force-
# refreshes via cache_set so weekday 18:30 IST always has fresh data.
CACHE_TTL_SECONDS = 24 * 60 * 60


async def _fetch_surveillance_uncached() -> dict:
    """Fetch ASM + GSM lists from NSE and merge into a flat flags map.

    Returns: ``{"flags": {symbol: "LTASM Stage I"|"STASM Stage II"|"GSM"},
                "as_of": "YYYY-MM-DD",
                "counts": {ltasm, stasm, gsm, errors}}``.

    Symbols not in either list are NOT in ``flags`` — callers treat
    absence as ``CLEAR``. Failure on one feed does not block the other:
    we always return whatever could be fetched, and log warnings for
    every error.
    """
    out: dict[str, str] = {}
    counts = {"ltasm": 0, "stasm": 0, "gsm": 0, "errors": 0}

    async with httpx.AsyncClient(
        timeout=15, headers=HEADERS, follow_redirects=True
    ) as client:
        # Bootstrap NSE session cookies via the landing pages. The site
        # homepage (`/`) returns 403 from OCI IPs, but the per-report
        # landing pages set the Akamai cookies their JSON endpoints
        # require. Each landing call is independent and best-effort.
        for landing in (ASM_LANDING, GSM_LANDING):
            try:
                await client.get(landing)
            except Exception as e:
                logger.warning("NSE landing bootstrap failed for %s: %s", landing, e)

        # ASM has TWO buckets in one payload — longterm and shortterm.
        # LTASM is the more severe tier at the same numeric stage.
        try:
            r = await client.get(ASM_URL, headers={"Referer": ASM_LANDING})
            if r.status_code == 200:
                payload = r.json()
                for bucket_key, prefix in (("longterm", "LTASM"), ("shortterm", "STASM")):
                    rows = (payload.get(bucket_key) or {}).get("data") or []
                    for row in rows:
                        sym = (row.get("symbol") or "").upper().strip()
                        stage = (row.get("asmSurvIndicator") or "").strip()
                        if sym and stage:
                            out[sym] = f"{prefix} {stage}"
                            counts["ltasm" if prefix == "LTASM" else "stasm"] += 1
            else:
                logger.warning("NSE /api/reportASM returned %s", r.status_code)
                counts["errors"] += 1
        except Exception as e:
            logger.warning("NSE ASM fetch failed: %s", e)
            counts["errors"] += 1

        # GSM is a flat list. The `gsmStage` field is a Roman-numeral
        # internal NSE counter (e.g. "LXII"), NOT the canonical 0-IV
        # regulatory stage — so v1 drops it and emits plain "GSM".
        # GSM trumps any ASM label since GSM is more severe.
        try:
            r = await client.get(GSM_URL, headers={"Referer": GSM_LANDING})
            if r.status_code == 200:
                rows = r.json() or []
                for row in rows:
                    sym = (row.get("symbol") or "").upper().strip()
                    if sym:
                        out[sym] = "GSM"
                        counts["gsm"] += 1
            else:
                logger.warning("NSE /api/reportGSM returned %s", r.status_code)
                counts["errors"] += 1
        except Exception as e:
            logger.warning("NSE GSM fetch failed: %s", e)
            counts["errors"] += 1

    return {
        "flags": out,
        "as_of": date.today().isoformat(),
        "counts": counts,
    }


async def get_surveillance_flags() -> dict[str, str]:
    """Cached daily — returns flat ``{symbol: flag_label}`` mapping.

    On any cache miss this hits NSE; subsequent calls within 24h are
    free. Callers should treat an empty dict as "no data" rather than
    "everything is clear" — distinguishing requires inspecting the
    cached payload's ``counts.errors`` if needed.
    """
    payload, _ = await cache_get_or_fetch(
        "nse:surveillance:asm_gsm",
        fetch_fn=_fetch_surveillance_uncached,
        ttl_seconds=CACHE_TTL_SECONDS,
    )
    return (payload or {}).get("flags") or {}


def get_reg_flag(symbol: str, flags_map: dict[str, str]) -> str:
    """Cheap per-symbol lookup with ``CLEAR`` default.

    Use this in tight per-row loops (e.g. building portfolio prompt
    rows) so the upstream surveillance map only gets fetched once."""
    return flags_map.get(symbol.upper().strip(), "CLEAR")
