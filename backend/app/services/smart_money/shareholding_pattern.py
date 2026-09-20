"""Quarterly shareholding pattern ingestion (NSE XBRL primary, BSE fallback).

Primary source: NSE XBRL filings published at nsearchives.nseindia.com.
The master API at /api/corporate-share-holdings-master returns filing
metadata with XBRL download URLs. The XML is parsed with stdlib
xml.etree.ElementTree — no lxml dependency.

Fallback: BSE corporate-action API (often blocked by Akamai anti-bot).

Tracks all symbols across watchlists + recent investment decisions.
For symbols where parsing fails, the run is marked partial — better to
land 80% than fail the whole batch on one vendor format drift.
"""

from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import async_session
from app.models.investment_decision import InvestmentDecision
from app.models.smart_money import ShareholdingPattern
from app.models.stock import Stock
from app.models.watchlist import WatchlistItem
from app.services.smart_money.deals import BSE_HEADERS
from app.services.smart_money.insider_disclosures import HEADERS as NSE_HEADERS

logger = logging.getLogger(__name__)

BSE_SHP_URL = "https://api.bseindia.com/BseIndiaAPI/api/CorporateAction/w"
NSE_SHP_MASTER_URL = "https://www.nseindia.com/api/corporate-share-holdings-master"
REQUEST_TIMEOUT = 60


def _parse_pct(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        s = str(v).replace("%", "").replace(",", "").strip()
        return float(s) if s else None
    except (ValueError, TypeError):
        return None


def _parse_quarter_label(d: date) -> str:
    """Return a YYYY-Q label like 'Q4-2026' from the quarter-end date."""
    q = (d.month - 1) // 3 + 1
    return f"Q{q}-{d.year}"


async def _symbols_to_track() -> list[tuple[str, str | None, str | None]]:
    """(symbol, isin, bse_code) for every symbol on a watchlist or in
    a recent investment-decision row. Empty list if no usable mapping."""
    cutoff = datetime.now().date() - timedelta(days=180)
    async with async_session() as session:
        # All watchlist symbols
        wl_q = await session.execute(
            select(WatchlistItem.symbol).distinct()
        )
        symbols = {row[0] for row in wl_q.all() if row[0]}

        # Plus investment_decisions (active research universe)
        id_q = await session.execute(
            select(InvestmentDecision.symbol).where(
                InvestmentDecision.created_at >= datetime.combine(cutoff, datetime.min.time())
            ).distinct()
        )
        symbols |= {row[0] for row in id_q.all() if row[0]}

        if not symbols:
            return []
        q2 = await session.execute(
            select(Stock.symbol, Stock.isin, getattr(Stock, "bse_code", Stock.symbol)).where(
                Stock.symbol.in_(symbols)
            )
        )
        out: list[tuple[str, str | None, str | None]] = []
        for sym, isin, bse in q2.all():
            out.append((sym, isin, bse if bse and bse != sym else None))
        return out


def _row_from_api(symbol: str, isin: str | None, payload: dict) -> dict | None:
    """Map a BSE shareholding-pattern API response item to our schema.

    The response shape (historically): a list under `Table`/`Table1` with
    rows for each shareholder category. We aggregate the four categories
    we care about. When the API drifts we return None so the caller marks
    the batch partial.
    """
    items = payload.get("Table") or payload.get("data") or []
    if not isinstance(items, list) or not items:
        return None

    # Each item has a category name + percentage. Parse them.
    cats: dict[str, float] = {}
    quarter_end_raw: str | None = None
    pledge_pct: float | None = None
    for it in items:
        cat = (it.get("CATEGORY_NAME") or it.get("Category") or "").strip().lower()
        pct = _parse_pct(it.get("Percent_Shareholding") or it.get("Percentage"))
        if pct is None:
            continue
        if "promoter" in cat and "group" in cat:
            cats["promoter"] = cats.get("promoter", 0.0) + pct
        elif "promoter" in cat:
            cats["promoter"] = cats.get("promoter", 0.0) + pct
        elif "fii" in cat or "fpi" in cat or "foreign" in cat:
            cats["fii"] = cats.get("fii", 0.0) + pct
        elif "mutual fund" in cat:
            cats.setdefault("mf", 0.0)
            cats["mf"] += pct
            cats.setdefault("dii", 0.0)
            cats["dii"] += pct
        elif "insurance" in cat:
            cats.setdefault("insurance", 0.0)
            cats["insurance"] += pct
            cats.setdefault("dii", 0.0)
            cats["dii"] += pct
        elif "domestic" in cat or "dii" in cat:
            cats["dii"] = cats.get("dii", 0.0) + pct
        elif "public" in cat or "non-promoter" in cat:
            cats["public"] = cats.get("public", 0.0) + pct
        # Pledge is sometimes carried alongside promoter rows
        ppct = _parse_pct(it.get("Promoter_Pledge_Pct") or it.get("PLEDGE_PERCENT"))
        if ppct is not None:
            pledge_pct = ppct
        if not quarter_end_raw:
            quarter_end_raw = it.get("AS_ON_DATE") or it.get("QuarterEndDate")

    if not quarter_end_raw or not cats:
        return None
    try:
        # Common formats: "31/03/2026", "2026-03-31"
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%b-%Y"):
            try:
                quarter_end = datetime.strptime(str(quarter_end_raw).split(" ")[0], fmt).date()
                break
            except ValueError:
                continue
        else:
            return None
    except Exception:
        return None

    return {
        "symbol": symbol,
        "isin": isin,
        "quarter": _parse_quarter_label(quarter_end),
        "quarter_end_date": quarter_end,
        "promoter_pct": cats.get("promoter"),
        "promoter_pledge_pct": pledge_pct,
        "fii_pct": cats.get("fii"),
        "dii_pct": cats.get("dii"),
        "mf_pct": cats.get("mf"),
        "insurance_pct": cats.get("insurance"),
        "public_pct": cats.get("public"),
        "exchange": "BSE",
        "raw_json": payload,
    }


async def _fetch_nse_filings_index(
    symbol: str, client: httpx.AsyncClient,
) -> list[dict]:
    """Fetch filing metadata from NSE master API. Returns list of dicts
    with keys like 'xbrl', 'date', 'period' etc."""
    try:
        resp = await client.get(
            NSE_SHP_MASTER_URL,
            params={"symbol": symbol, "index": "equities"},
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.debug("NSE shareholding index failed for %s: %s", symbol, e)
        return []


def _parse_xbrl_shareholding(xml_bytes: bytes) -> dict[str, float | None]:
    """Parse an NSE XBRL shareholding XML and extract category percentages.

    The XBRL uses a single element name `ShareholdingAsAPercentageOfTotalNumberOfShares`
    for all categories, differentiated by `contextRef`. Summary-level contexts
    end with `_ContextI`. Values are fractions (0.288 = 28.8%) — we convert to
    percentages for consistency with the rest of the codebase.

    Returns dict with keys: promoter, fii, dii, mf, insurance, public, pledge."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return {}

    # Build a map of contextRef → value for all ShareholdingAsAPercentage elements
    ctx_map: dict[str, float] = {}
    for elem in root.iter():
        local = elem.tag.rsplit("}", 1)[-1] if "}" in elem.tag else elem.tag
        if local == "ShareholdingAsAPercentageOfTotalNumberOfShares":
            ctx = elem.get("contextRef", "")
            try:
                ctx_map[ctx] = float(elem.text)
            except (TypeError, ValueError):
                continue

    CONTEXT_MAPPING = {
        "promoter": "ShareholdingOfPromoterAndPromoterGroup_ContextI",
        "fii": "InstitutionsForeign_ContextI",
        "dii": "InstitutionsDomestic_ContextI",
        "mf": "MutualFundsOrUTI_ContextI",
        "insurance": "InsuranceCompanies_ContextI",
        "public": "NonInstitutions_ContextI",
    }

    out: dict[str, float | None] = {}
    for key, ctx_ref in CONTEXT_MAPPING.items():
        val = ctx_map.get(ctx_ref)
        # Convert fraction to percentage (0.288 → 28.8).
        # Missing category with other data present → 0 (e.g. Eternal has no promoter group).
        out[key] = round(val * 100, 2) if val is not None else (0.0 if ctx_map else None)

    # Pledge: look for encumbrance percentage elements only.
    # Raw share counts can be very large — only accept values ≤ 100.
    pledge = None
    for elem in root.iter():
        local = elem.tag.rsplit("}", 1)[-1] if "}" in elem.tag else elem.tag
        if ("Pledge" in local or "Encumbered" in local) and "Percentage" in local:
            try:
                val = float(elem.text)
                if 0 < val <= 1:
                    pledge = round(val * 100, 2)
                    break
                elif 0 < val <= 100:
                    pledge = round(val, 2)
                    break
            except (TypeError, ValueError):
                continue
    out["pledge"] = pledge

    return out


def _parse_xbrl_quarter_end(xml_bytes: bytes) -> date | None:
    """Extract the quarter-end date from XBRL period endDate."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None

    ns = {"xbrli": "http://www.xbrl.org/2003/instance"}
    for period in root.iter("{http://www.xbrl.org/2003/instance}period"):
        end_elem = period.find("xbrli:endDate", ns)
        if end_elem is not None and end_elem.text:
            try:
                return datetime.strptime(end_elem.text.strip(), "%Y-%m-%d").date()
            except ValueError:
                continue
    return None


def _row_from_nse_xbrl(
    symbol: str, isin: str | None, parsed: dict[str, float | None],
    quarter_end: date, xbrl_url: str,
) -> dict | None:
    """Map parsed XBRL data to ShareholdingPattern schema."""
    if not parsed.get("promoter") and not parsed.get("fii"):
        return None
    return {
        "symbol": symbol,
        "isin": isin,
        "quarter": _parse_quarter_label(quarter_end),
        "quarter_end_date": quarter_end,
        "promoter_pct": parsed.get("promoter"),
        "promoter_pledge_pct": parsed.get("pledge"),
        "fii_pct": parsed.get("fii"),
        "dii_pct": parsed.get("dii"),
        "mf_pct": parsed.get("mf"),
        "insurance_pct": parsed.get("insurance"),
        "public_pct": parsed.get("public"),
        "exchange": "NSE",
        "raw_json": {"source": "nse_xbrl", "xbrl_url": xbrl_url},
    }


async def _fetch_nse_shareholding(
    symbol: str, isin: str | None, client: httpx.AsyncClient,
) -> dict | None:
    """Fetch the latest NSE XBRL shareholding filing for a symbol.
    Returns a row dict ready for _persist_with_deltas, or None on failure."""
    filings = await _fetch_nse_filings_index(symbol, client)
    if not filings:
        return None

    # Find the latest filing with an XBRL URL
    xbrl_url = None
    for filing in filings:
        url = filing.get("xbrl") or filing.get("xbrlFile") or filing.get("fileName")
        if url:
            if not url.startswith("http"):
                url = f"https://nsearchives.nseindia.com{url}" if url.startswith("/") else f"https://nsearchives.nseindia.com/{url}"
            xbrl_url = url
            break

    if not xbrl_url:
        logger.debug("No XBRL URL found in NSE filings for %s", symbol)
        return None

    try:
        xbrl_resp = await client.get(xbrl_url, timeout=30)
        xbrl_resp.raise_for_status()
    except Exception as e:
        logger.debug("XBRL download failed for %s: %s", symbol, e)
        return None

    xml_bytes = xbrl_resp.content
    parsed = _parse_xbrl_shareholding(xml_bytes)
    if not parsed:
        return None

    quarter_end = _parse_xbrl_quarter_end(xml_bytes)
    if not quarter_end:
        # Try to extract from filing metadata
        for filing in filings:
            date_str = filing.get("date") or filing.get("toDate") or filing.get("period")
            if date_str:
                for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
                    try:
                        quarter_end = datetime.strptime(str(date_str).strip(), fmt).date()
                        break
                    except ValueError:
                        continue
            if quarter_end:
                break

    if not quarter_end:
        logger.debug("Could not determine quarter-end date from XBRL for %s", symbol)
        return None

    return _row_from_nse_xbrl(symbol, isin, parsed, quarter_end, xbrl_url)


async def _persist_with_deltas(rows: list[dict]) -> tuple[int, int, int]:
    """Compute promoter/fii/dii/pledge deltas vs the previous quarter row
    for the same (symbol, exchange), then upsert."""
    if not rows:
        return (0, 0, 0)

    inserted = 0
    skipped = 0
    async with async_session() as session:
        for r in rows:
            prev_q = await session.execute(
                select(ShareholdingPattern)
                .where(
                    ShareholdingPattern.symbol == r["symbol"],
                    ShareholdingPattern.exchange == r["exchange"],
                    ShareholdingPattern.quarter_end_date < r["quarter_end_date"],
                )
                .order_by(ShareholdingPattern.quarter_end_date.desc())
                .limit(1)
            )
            prev = prev_q.scalar_one_or_none()
            if prev is not None:
                def _delta(curr: float | None, old: Decimal | float | None) -> float | None:
                    if curr is None or old is None:
                        return None
                    return float(curr) - float(old)

                r["promoter_delta"] = _delta(r.get("promoter_pct"), prev.promoter_pct)
                r["fii_delta"] = _delta(r.get("fii_pct"), prev.fii_pct)
                r["dii_delta"] = _delta(r.get("dii_pct"), prev.dii_pct)
                r["pledge_delta"] = _delta(r.get("promoter_pledge_pct"), prev.promoter_pledge_pct)

            stmt = pg_insert(ShareholdingPattern).values(**r)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["symbol", "quarter_end_date", "exchange"]
            )
            result = await session.execute(stmt)
            if result.rowcount:
                inserted += 1
            else:
                skipped += 1
        await session.commit()

    return (inserted, 0, skipped)


async def sync_shareholding_patterns() -> dict:
    """Fetch shareholding for each tracked symbol.

    Strategy: try NSE XBRL first (primary, more reliable), fall back to
    BSE API for symbols where NSE fails. Rate-limits NSE requests with
    a 2s delay between symbols.
    """
    targets = await _symbols_to_track()
    if not targets:
        return {"fetched": 0, "inserted": 0, "updated": 0, "skipped": 0, "note": "no targets"}

    rows: list[dict] = []
    bytes_total = 0
    failures = 0
    nse_ok = 0
    bse_ok = 0

    # Phase 1: NSE XBRL (primary)
    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT, headers=NSE_HEADERS, follow_redirects=True,
    ) as nse_client:
        try:
            await nse_client.get("https://www.nseindia.com", timeout=15)
        except Exception:
            pass

        nse_failed_symbols: list[tuple[str, str | None, str | None]] = []
        for symbol, isin, bse_code in targets:
            row = await _fetch_nse_shareholding(symbol, isin, nse_client)
            if row is not None:
                rows.append(row)
                nse_ok += 1
            else:
                nse_failed_symbols.append((symbol, isin, bse_code))
            await asyncio.sleep(2)

    # Phase 2: BSE fallback for NSE failures
    if nse_failed_symbols:
        bse_targets = [(s, i, b) for s, i, b in nse_failed_symbols if b]
        if bse_targets:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT, headers=BSE_HEADERS, follow_redirects=True,
            ) as bse_client:
                try:
                    await bse_client.get("https://www.bseindia.com", timeout=15)
                except Exception:
                    pass

                for symbol, isin, bse_code in bse_targets:
                    try:
                        resp = await bse_client.get(
                            BSE_SHP_URL,
                            params={"scripcode": bse_code, "segment": "0", "status": "current"},
                        )
                        resp.raise_for_status()
                        bytes_total += len(resp.content)
                        payload = resp.json()
                    except Exception as e:
                        failures += 1
                        logger.debug("BSE shareholding failed for %s/%s: %s", symbol, bse_code, e)
                        continue

                    row = _row_from_api(symbol, isin, payload)
                    if row is not None:
                        rows.append(row)
                        bse_ok += 1
                    else:
                        failures += 1

        failures += len(nse_failed_symbols) - len(bse_targets) - bse_ok

    inserted, _, skipped = await _persist_with_deltas(rows)
    return {
        "fetched": len(rows),
        "inserted": inserted,
        "updated": 0,
        "skipped": skipped,
        "bytes": bytes_total,
        "failures": failures,
        "targets": len(targets),
        "nse_ok": nse_ok,
        "bse_ok": bse_ok,
    }
