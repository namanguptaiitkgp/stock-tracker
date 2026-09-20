"""Screener.in scraper for Indian stock fundamentals.

Extracts ~22 metrics from screener.in/company/{SYMBOL}/consolidated/.
Results are cached 24h via data_cache. Used by both metric_engine
(via metric_sources/screener_source.py) and fundamentals_service.py.
"""

import logging
import os
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.services.data_cache import cache_get_or_fetch
from app.services.screener_presets import normalize_sector

logger = logging.getLogger(__name__)

_CACHE_TTL = 86400  # 24 hours

# Screener.in is reachable directly from residential IPs but blocked at the
# TCP layer from cloud-provider ranges (OCI / AWS / GCP). When both
# SCREENER_PROXY_URL and SCREENER_PROXY_SECRET are set, we route the fetch
# through a Cloudflare Worker that re-fetches from Cloudflare's edge and
# authenticates incoming requests with X-Proxy-Auth. See
# `cloudflare-workers/screener-proxy/` for the Worker source + SETUP.md.
#
# Locally:  leave both unset (direct upstream).
# On OCI:   set both in .env.oci.
_UPSTREAM = "https://www.screener.in"
SCREENER_PROXY_URL = (os.environ.get("SCREENER_PROXY_URL", "") or "").rstrip("/") or None
SCREENER_PROXY_SECRET = os.environ.get("SCREENER_PROXY_SECRET") or None

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _safe_float(text: str | None) -> float | None:
    if not text:
        return None
    text = text.strip().replace(",", "").replace("%", "").replace("₹", "").replace("+", "").strip()
    if not text or text == "—":
        return None
    try:
        f = float(text)
        return None if f != f else f
    except (ValueError, TypeError):
        return None


def _get_table_data(soup: BeautifulSoup, section_id: str) -> dict[str, list[float | None]]:
    section = soup.find("section", id=section_id)
    if not section:
        return {}
    table = section.find("table")
    if not table:
        return {}
    data: dict[str, list[float | None]] = {}
    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        label = cells[0].get_text(strip=True).rstrip("+").strip()
        if not label:
            continue
        data[label] = [_safe_float(c.get_text(strip=True)) for c in cells[1:]]
    return data


def _extract_taxonomy(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Screener.in renders a 4-level taxonomy in the company header as anchors
    with `title="Broad Sector"` → `"Sector"` → `"Broad Industry"` → `"Industry"`.

    Example for TCS:
        Broad Sector:   "Information Technology"
        Sector:         "Information Technology"
        Broad Industry: "IT - Software"
        Industry:       "Computers - Software & Consulting"

    Returns (sector, industry) where:
      • sector is normalized to one of the 11 canonical sectors via
        normalize_sector(); we prefer "Broad Sector" since it aligns best
        with the canonical taxonomy, falling back to "Sector" or
        "Broad Industry" when missing.
      • industry is the raw, fine-grained label kept verbatim (used for
        peer matching and sub-sector breakdowns later).
    """
    sector_raw = None
    for title_attr in ("Broad Sector", "Sector", "Broad Industry"):
        a = soup.find("a", attrs={"title": title_attr})
        if a:
            txt = a.get_text(strip=True)
            if txt:
                sector_raw = txt
                break

    industry_raw = None
    for title_attr in ("Industry", "Broad Industry"):
        a = soup.find("a", attrs={"title": title_attr})
        if a:
            txt = a.get_text(strip=True)
            if txt:
                industry_raw = txt
                break

    return normalize_sector(sector_raw), industry_raw


def _parse(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, Any] = {}

    # ── Sector + Industry (header taxonomy) ──────────────────────────
    sector, industry = _extract_taxonomy(soup)
    if sector:
        out["sector"] = sector
    if industry:
        out["industry"] = industry

    # ── #top-ratios ──────────────────────────────────────────────────
    top = soup.find(id="top-ratios")
    if top:
        for li in top.find_all("li"):
            name_el = li.find("span", class_="name")
            val_el = li.find("span", class_="number")
            if not name_el or not val_el:
                continue
            name = name_el.get_text(strip=True)
            val = _safe_float(val_el.get_text(strip=True))
            if val is None:
                continue
            if "Market Cap" in name:
                out["market_cap"] = val
            elif name == "Stock P/E":
                out["pe_ratio"] = val
            elif name == "ROCE":
                out["roce"] = val / 100
            elif name == "ROE":
                out["roe"] = val / 100
            elif "Div" in name and "Yield" in name:
                out["dividend_yield"] = val / 100
            elif "Book Value" in name:
                out["_book_value"] = val

    # ── #balance-sheet → D/E, ROA ────────────────────────────────────
    bs = _get_table_data(soup, "balance-sheet")
    borrowings = equity = reserves = total_assets = None
    for label, vals in bs.items():
        if not vals:
            continue
        if label in ("Borrowings", "Borrowing"):
            borrowings = vals[-1]
        elif label == "Equity Capital":
            equity = vals[-1]
        elif label == "Reserves":
            reserves = vals[-1]
        elif label == "Total Assets":
            total_assets = vals[-1]

    if borrowings is not None and equity is not None and reserves is not None:
        total_equity = equity + reserves
        if total_equity > 0:
            out["debt_to_equity"] = borrowings / total_equity

    # ── #profit-loss → growth, margins ───────────────────────────────
    pl = _get_table_data(soup, "profit-loss")
    sales = pl.get("Sales") or pl.get("Revenue")
    net_profit = pl.get("Net Profit")
    eps = pl.get("EPS in Rs")
    op_profit = pl.get("Operating Profit")

    if sales and len(sales) >= 2 and sales[-1] and sales[-2] and sales[-2] != 0:
        out["revenue_growth_1y"] = (sales[-1] - sales[-2]) / abs(sales[-2])
    if net_profit and sales and net_profit[-1] is not None and sales[-1] and sales[-1] != 0:
        out["net_profit_margin"] = net_profit[-1] / sales[-1]
    if eps and len(eps) >= 2 and eps[-1] and eps[-2] and eps[-2] != 0:
        out["eps_growth_1y"] = (eps[-1] - eps[-2]) / abs(eps[-2])
    if op_profit and sales and op_profit[-1] is not None and sales[-1] and sales[-1] != 0:
        out["ebitda_margin"] = op_profit[-1] / sales[-1]

    # EPS 5Y CAGR (need 6+ years of data)
    if eps and len(eps) >= 6:
        e_new = eps[-1]
        e_old = eps[-6]
        if e_new and e_old and e_old > 0 and e_new > 0:
            out["eps_growth_5y"] = (e_new / e_old) ** (1 / 5) - 1

    # ROA = Net Profit / Total Assets
    if net_profit and net_profit[-1] is not None and total_assets and total_assets != 0:
        out["return_on_assets"] = net_profit[-1] / total_assets

    # ── #cash-flow ───────────────────────────────────────────────────
    cf = _get_table_data(soup, "cash-flow")
    ocf_row = cf.get("Cash from Operating Activity")
    fcf_row = cf.get("Free Cash Flow")

    if ocf_row and ocf_row[-1] is not None:
        out["operating_cash_flow"] = ocf_row[-1]
        if sales and sales[-1] and sales[-1] != 0:
            out["cash_flow_margin"] = ocf_row[-1] / sales[-1]
    if fcf_row and fcf_row[-1] is not None:
        out["free_cash_flow"] = fcf_row[-1]

    # ── #shareholding ────────────────────────────────────────────────
    sh_section = soup.find("section", id="shareholding")
    if sh_section:
        table = sh_section.find("table")
        if table:
            thead = table.find("thead") or table.find("tr")
            headers = [th.get_text(strip=True) for th in thead.find_all("th")] if thead else []
            quarters = headers[1:] if len(headers) >= 2 else []

            rows_data: dict[str, list[float | None]] = {}
            for row in table.find_all("tr"):
                cells = row.find_all("td")
                if not cells:
                    continue
                label = cells[0].get_text(strip=True)
                values = [_safe_float(c.get_text(strip=True)) for c in cells[1:]]
                if "Promoter" in label and "Pledge" not in label:
                    rows_data["promoter"] = values
                elif "FII" in label or "Foreign" in label:
                    rows_data["fii"] = values
                elif "DII" in label:
                    rows_data["dii"] = values
                elif "Public" in label:
                    rows_data["retail"] = values
                elif "Pledge" in label:
                    rows_data["pledge"] = values

            if rows_data.get("promoter"):
                out["promoter_holding"] = rows_data["promoter"][0]
                if len(rows_data["promoter"]) >= 2:
                    p0, p1 = rows_data["promoter"][0], rows_data["promoter"][1]
                    if p0 is not None and p1 is not None:
                        out["promoter_holding_change_3m"] = p0 - p1
            if rows_data.get("fii"):
                out["fii_holding"] = rows_data["fii"][0]
                if len(rows_data["fii"]) >= 2:
                    f0, f1 = rows_data["fii"][0], rows_data["fii"][1]
                    if f0 is not None and f1 is not None:
                        out["fii_holding_change_3m"] = f0 - f1
            if rows_data.get("dii"):
                out["dii_holding"] = rows_data["dii"][0]

            # Build shareholding_history JSON array
            history: list[dict[str, Any]] = []
            for i, q in enumerate(quarters):
                entry: dict[str, Any] = {"q": q, "mf": None}
                for key in ("promoter", "fii", "dii", "retail", "pledge"):
                    vals = rows_data.get(key, [])
                    entry[key] = vals[i] if i < len(vals) else None
                history.append(entry)
            if history:
                out["shareholding_history"] = history

    # Strip internal keys
    return {k: v for k, v in out.items() if not k.startswith("_")}


async def _fetch_raw(symbol: str) -> dict[str, Any] | None:
    targets = [
        f"{_UPSTREAM}/company/{symbol}/consolidated/",
        f"{_UPSTREAM}/company/{symbol}/",
    ]
    use_proxy = bool(SCREENER_PROXY_URL and SCREENER_PROXY_SECRET)
    async with httpx.AsyncClient(timeout=15, headers=_HEADERS, follow_redirects=True) as client:
        for target in targets:
            if use_proxy:
                resp = await client.get(
                    SCREENER_PROXY_URL,
                    params={"url": target},
                    headers={"X-Proxy-Auth": SCREENER_PROXY_SECRET},
                )
                # A bad/missing secret will reject every request — fail loud
                # and short-circuit instead of burning the consolidated/
                # standalone retry on the same broken auth.
                if resp.status_code == 401:
                    logger.error(
                        "screener_proxy: 401 Unauthorized — check SCREENER_PROXY_SECRET"
                    )
                    return None
            else:
                resp = await client.get(target)
            if resp.status_code == 200:
                return _parse(resp.text)
    return None


async def fetch_fundamentals(symbol: str) -> dict[str, Any] | None:
    """Fetch fundamentals for a symbol from Screener.in (cached 24h).

    Returns a flat dict of {metric_key: value} or None on failure.
    Values use canonical units: ratios as decimals (0.15 = 15%),
    monetary values in Crores, shareholding in percentage points.
    """
    symbol = symbol.upper().strip()
    cache_key = f"screener:{symbol}"
    try:
        payload, _ = await cache_get_or_fetch(
            cache_key,
            lambda: _fetch_raw(symbol),
            ttl_seconds=_CACHE_TTL,
        )
        if payload and isinstance(payload, dict):
            return payload
        return None
    except Exception:
        logger.warning("Screener fetch failed for %s", symbol, exc_info=True)
        return None
