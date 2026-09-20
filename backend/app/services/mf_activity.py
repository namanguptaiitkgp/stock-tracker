import asyncio
import json
import logging
import re
from collections import OrderedDict

import httpx

from app.services.tickertape_fetcher import _discover_slug, HEADERS as TT_HEADERS

logger = logging.getLogger(__name__)

MFDATA_BASE = "https://mfdata.in/api/v1"

# Map NSE symbols to company names used by mfdata.in (e.g. "HDFC Bank Ltd").
# Bounded LRU — capped at the size of the NSE/BSE universe so a long-running
# process can't OOM on accumulated lookups.
_NAME_CACHE_MAX = 8192
_name_cache: "OrderedDict[str, str | None]" = OrderedDict()


def _name_cache_set(symbol: str, value: str | None) -> None:
    if symbol in _name_cache:
        _name_cache.move_to_end(symbol)
    _name_cache[symbol] = value
    while len(_name_cache) > _NAME_CACHE_MAX:
        _name_cache.popitem(last=False)


async def get_mf_activity(symbol: str) -> dict | None:
    """Fetch mutual fund holding activity from Tickertape (shareholding pattern)."""
    slug = await _discover_slug(symbol.upper())
    if not slug:
        return None

    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=TT_HEADERS) as client:
            resp = await client.get(f"https://www.tickertape.in/stocks/{slug}")
            if resp.status_code != 200:
                return None

            html = resp.text
            match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if not match:
                return None

            next_data = json.loads(match.group(1))
            base = _extract_mf_data(next_data) or {}
            base["holding_history"] = _extract_holding_history(next_data)
            base["top_mf_funds"] = _extract_mf_rankings(next_data)
            base["narratives"] = _extract_holding_narratives(next_data)
            base["available"] = bool(base.get("holding_history") or base.get("top_mf_funds"))
            return base

    except Exception as e:
        logger.warning(f"MF activity fetch failed for {symbol}: {e}")
        return None


def _extract_holding_history(next_data: dict) -> list[dict]:
    """Quarter-by-quarter shareholding breakdown from
    securitySummary.holdings.holdings. Returns newest-first with pct
    deltas vs the prior quarter already computed.

    Upstream keys of interest (all % of total):
        pmPctT  — Promoter total
        pmPctP  — Promoter pledged %
        plPctT  — Total pledged
        uPlPctT — Unpledged promoter
        mfPctT  — Mutual funds
        fiPctT  — Foreign institutions (FII/FPI)
        isPctT  — Insurance
        diPctT  — Domestic institutions (total)
        rhPctT  — Retail
        othPctT — Others
    """
    try:
        props = next_data.get("props", {}).get("pageProps", {})
        summary = props.get("securitySummary", {})
        holdings = summary.get("holdings", {}).get("holdings", [])
        if not holdings:
            return []
        # holdings is list of {date, data}. Sort newest-first.
        sorted_h = sorted(
            [h for h in holdings if h.get("date") and h.get("data")],
            key=lambda x: x["date"],
            reverse=True,
        )
        rows: list[dict] = []
        for h in sorted_h:
            d = h["data"] or {}
            rows.append({
                "date": h["date"][:10],
                "promoter_pct": round(float(d.get("pmPctT") or 0), 3) if d.get("pmPctT") is not None else None,
                "promoter_pledged_pct": round(float(d.get("pmPctP") or 0), 3) if d.get("pmPctP") is not None else None,
                "pledged_total_pct": round(float(d.get("plPctT") or 0), 3) if d.get("plPctT") is not None else None,
                "mf_pct": round(float(d.get("mfPctT") or 0), 3) if d.get("mfPctT") is not None else None,
                "fii_pct": round(float(d.get("fiPctT") or 0), 3) if d.get("fiPctT") is not None else None,
                "di_pct": round(float(d.get("diPctT") or 0), 3) if d.get("diPctT") is not None else None,
                "insurance_pct": round(float(d.get("isPctT") or 0), 3) if d.get("isPctT") is not None else None,
                "retail_pct": round(float(d.get("rhPctT") or 0), 3) if d.get("rhPctT") is not None else None,
                "other_pct": round(float(d.get("othPctT") or 0), 3) if d.get("othPctT") is not None else None,
            })
        # Compute deltas vs prior quarter
        for i, row in enumerate(rows):
            if i + 1 >= len(rows):
                row["delta_prev"] = None
                continue
            prev = rows[i + 1]
            row["delta_prev"] = {
                k.replace("_pct", ""): round((row[k] - prev[k]), 3) if row.get(k) is not None and prev.get(k) is not None else None
                for k in ("promoter_pct", "mf_pct", "fii_pct", "di_pct", "retail_pct", "insurance_pct", "pledged_total_pct")
            }
        return rows
    except Exception as e:
        logger.warning(f"Holding history extraction failed: {e}")
        return []


def _extract_mf_rankings(next_data: dict) -> list[dict]:
    """Top MFs that hold the stock — each row has weight, 3m change, rank."""
    try:
        props = next_data.get("props", {}).get("pageProps", {})
        summary = props.get("securitySummary", {})
        mf = summary.get("mfHoldings") or []
        if not isinstance(mf, list):
            return []
        out: list[dict] = []
        for row in mf:
            if not isinstance(row, dict):
                continue
            meta = row.get("meta") or {}
            out.append({
                "fund_name": meta.get("name") or meta.get("fullName") or "",
                "fund_full_name": meta.get("fullName") or "",
                "mf_id": meta.get("mfId"),
                "isin": meta.get("isin"),
                "weight": _f(row.get("weight")),
                "market_cap_pct": _f(row.get("marketCapPct")),
                "change_3m": _f(row.get("change3m")),
                "current_rank": row.get("currentRank"),
                "prev_rank": row.get("prevRank"),
            })
        # Sort newest movers first (largest |change_3m|), then by weight
        out.sort(
            key=lambda r: (-abs(r.get("change_3m") or 0), -(r.get("weight") or 0))
        )
        return out[:20]
    except Exception as e:
        logger.warning(f"MF rankings extraction failed: {e}")
        return []


def _extract_holding_narratives(next_data: dict) -> list[dict]:
    """Tickertape's pre-written insight bullets about holdings changes."""
    try:
        props = next_data.get("props", {}).get("pageProps", {})
        summary = props.get("securitySummary", {})
        items = summary.get("shareHoldings") or []
        out = []
        for it in items:
            if not isinstance(it, dict):
                continue
            out.append({
                "title": it.get("title"),
                "message": it.get("message"),
                "description": it.get("description"),
                "mood": it.get("mood"),
            })
        return out
    except Exception:
        return []


def _f(v) -> float | None:
    if v is None:
        return None
    try:
        return round(float(v), 4)
    except (TypeError, ValueError):
        return None


def _extract_mf_data(next_data: dict) -> dict | None:
    """Extract mutual fund holding data from Tickertape __NEXT_DATA__."""
    try:
        props = next_data.get("props", {}).get("pageProps", {})
        summary = props.get("securitySummary", {})
        holdings = summary.get("shareHoldings", [])
        mf_data = summary.get("holdings", {}).get("holdings", [])

        mf_holding_pct = None
        fii_holding_pct = None
        promoter_pct = None
        public_pct = None

        for h in holdings:
            if not isinstance(h, dict):
                continue
            name = (h.get("name") or h.get("category") or "").lower()
            value = h.get("value") or h.get("percentage")
            if value is None:
                continue
            try:
                val = float(value)
            except (TypeError, ValueError):
                continue

            if "mutual" in name or "mf" in name:
                mf_holding_pct = val
            elif "fii" in name or "fpi" in name or "foreign" in name:
                fii_holding_pct = val
            elif "promoter" in name:
                promoter_pct = val
            elif "public" in name:
                public_pct = val

        mf_names = []
        for m in mf_data:
            if isinstance(m, dict):
                name = m.get("name") or m.get("schemeName")
                if name:
                    mf_names.append(str(name))

        if mf_holding_pct is None and not mf_names:
            return None

        return {
            "mf_holding_pct": mf_holding_pct,
            "fii_holding_pct": fii_holding_pct,
            "promoter_pct": promoter_pct,
            "public_pct": public_pct,
            "mf_count": len(mf_names),
            "top_mf_holders": mf_names[:5],
        }

    except Exception as e:
        logger.warning(f"MF data extraction failed: {e}")
        return None


async def get_mf_buysell(symbol: str, company_name: str | None = None) -> dict | None:
    """Fetch MF buy/sell activity from mfdata.in.
    Returns which MFs hold this stock, and for top holders, the month-over-month changes."""

    # Step 1: Find the stock name used by mfdata.in
    stock_name = await _resolve_stock_name(symbol, company_name)
    if not stock_name:
        return None

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Step 2: Get all MF holders of this stock
            resp = await client.get(f"{MFDATA_BASE}/stocks/{stock_name}/holders")
            if resp.status_code != 200:
                logger.warning(f"mfdata.in holders returned {resp.status_code} for '{stock_name}'")
                return None

            data = resp.json()
            holders = data.get("data", [])
            if not holders:
                return None

            # Step 3: Get month-over-month changes for top active fund holders
            # Filter to active funds (exclude index funds and ETFs)
            active_holders = [
                h for h in holders
                if h.get("category") and "Index" not in str(h.get("category", ""))
                and "ETF" not in str(h.get("family_name", ""))
            ]
            # If no active funds, use all
            if not active_holders:
                active_holders = holders

            # Sort by market value (largest holders first)
            active_holders.sort(key=lambda h: h.get("market_value") or 0, reverse=True)
            top_holders = active_holders[:15]

            # Step 4: Fetch family holdings for top holders to get month_change_qty
            changes = await _fetch_holder_changes(client, top_holders, stock_name)

            # Step 5: Aggregate
            added = [c for c in changes if c["change_type"] == "added"]
            reduced = [c for c in changes if c["change_type"] == "reduced"]
            new_entry = [c for c in changes if c["change_type"] == "new"]
            exited = [c for c in changes if c["change_type"] == "exited"]
            unchanged = [c for c in changes if c["change_type"] == "unchanged"]

            return {
                "stock_name": stock_name,
                "total_mf_holders": len(holders),
                "active_fund_holders": len(active_holders),
                "month": holders[0].get("month") if holders else None,
                "summary": {
                    "added": len(added),
                    "reduced": len(reduced),
                    "new_entry": len(new_entry),
                    "exited": len(exited),
                    "unchanged": len(unchanged),
                },
                "changes": changes[:10],  # Top 10 changes
            }

    except Exception as e:
        logger.warning(f"MF buy/sell fetch failed for {symbol}: {e}")
        return None


async def _resolve_stock_name(symbol: str, company_name: str | None) -> str | None:
    """Resolve NSE symbol to the stock name used by mfdata.in."""
    symbol = symbol.upper()
    if symbol in _name_cache:
        _name_cache.move_to_end(symbol)
        return _name_cache[symbol]

    # Try the company name from fundamentals (e.g., "HDFC Bank Ltd")
    if company_name:
        # mfdata.in uses names like "HDFC Bank Ltd" — try as-is first
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{MFDATA_BASE}/stocks/{company_name}/holders")
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("data"):
                        _name_cache_set(symbol, company_name)
                        return company_name
        except Exception:
            pass

        # Try variants: add "Ltd" if not present
        for variant in [f"{company_name} Ltd", f"{company_name} Limited", company_name.replace(" Limited", " Ltd")]:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(f"{MFDATA_BASE}/stocks/{variant}/holders")
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("data"):
                            _name_cache_set(symbol, variant)
                            return variant
            except Exception:
                pass

    _name_cache_set(symbol, None)
    return None


async def _fetch_holder_changes(
    client: httpx.AsyncClient,
    holders: list[dict],
    stock_name: str,
) -> list[dict]:
    """For each holder, fetch their family holdings to get month_change_qty."""
    changes = []

    # Limit concurrency
    sem = asyncio.Semaphore(5)

    async def fetch_one(holder: dict):
        async with sem:
            family_id = holder.get("family_id")
            if not family_id:
                return None
            try:
                resp = await client.get(f"{MFDATA_BASE}/families/{family_id}/holdings", timeout=15)
                if resp.status_code != 200:
                    return None

                data = resp.json()
                equity_holdings = data.get("data", {}).get("equity_holdings", [])

                # Find our stock in this fund's holdings
                for eh in equity_holdings:
                    if eh.get("stock_name", "").lower() == stock_name.lower():
                        qty = eh.get("quantity", 0)
                        change_qty = eh.get("month_change_qty", 0)
                        change_pct = eh.get("month_change_pct", 0)

                        if change_qty > 0:
                            change_type = "added"
                        elif change_qty < 0:
                            change_type = "reduced"
                        elif qty > 0 and change_qty == 0:
                            change_type = "unchanged"
                        else:
                            change_type = "unchanged"

                        return {
                            "fund_name": holder.get("family_name", "Unknown"),
                            "amc": holder.get("amc_name", ""),
                            "category": holder.get("category", ""),
                            "quantity": qty,
                            "change_qty": change_qty,
                            "change_pct": round(change_pct, 2) if change_pct else 0,
                            "market_value": eh.get("market_value"),
                            "weight_pct": eh.get("weight_pct"),
                            "change_type": change_type,
                        }

                # Stock not found in holdings — might have exited
                return {
                    "fund_name": holder.get("family_name", "Unknown"),
                    "amc": holder.get("amc_name", ""),
                    "category": holder.get("category", ""),
                    "quantity": 0,
                    "change_qty": -(holder.get("quantity") or 0),
                    "change_pct": -100,
                    "change_type": "exited",
                }

            except Exception:
                return None

    results = await asyncio.gather(*[fetch_one(h) for h in holders], return_exceptions=True)

    for r in results:
        if isinstance(r, dict):
            changes.append(r)

    # Sort: biggest changes first (by absolute change_qty)
    changes.sort(key=lambda c: abs(c.get("change_qty", 0)), reverse=True)
    return changes
