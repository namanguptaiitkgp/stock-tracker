from fastapi import APIRouter, Depends, HTTPException
from kiteconnect import KiteConnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.services.fundamentals_service import get_cached_fundamentals_bulk
from app.services.portfolio_cache import get_holdings as cached_holdings

router = APIRouter()


def _cap_bucket_cr(market_cap_cr: float | None) -> str:
    """SEBI-aligned retail buckets in ₹ crore."""
    if market_cap_cr is None or market_cap_cr <= 0:
        return "unknown"
    if market_cap_cr >= 20_000:
        return "large"
    if market_cap_cr >= 5_000:
        return "mid"
    return "small"


@router.get("/exposure")
async def get_portfolio_exposure(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Aggregated risk view: sector concentration, cap-bucket distribution,
    Herfindahl concentration index, top-N share. Pure SQL — no LLM."""
    from app.services.portfolio_cache import holding_total_qty
    try:
        holdings = await cached_holdings(user)
    except Exception:
        holdings = []

    # Build position values: qty * LTP (fall back to avg_price if last_price missing).
    positions: list[dict] = []
    for h in holdings:
        qty = holding_total_qty(h)
        if qty <= 0:
            continue
        ltp = h.get("last_price") or h.get("close_price") or h.get("average_price") or 0
        sym = (h.get("tradingsymbol") or "").upper().strip()
        if not sym:
            continue
        positions.append({"symbol": sym, "value": qty * float(ltp)})

    total_value = sum(p["value"] for p in positions)
    if total_value <= 0:
        return {
            "total_value": 0,
            "by_sector": [], "by_cap_bucket": [],
            "top_n": [], "herfindahl": 0,
            "position_count": 0,
        }

    symbols = [p["symbol"] for p in positions]
    fund_map = await get_cached_fundamentals_bulk(symbols, db)

    # Sector aggregation
    sector_acc: dict[str, float] = {}
    cap_acc: dict[str, float] = {}
    for p in positions:
        f = fund_map.get(p["symbol"])
        sector = (f.sector if f and f.sector else "Unknown")
        sector_acc[sector] = sector_acc.get(sector, 0.0) + p["value"]
        cap_bucket = _cap_bucket_cr(float(f.market_cap) if (f and f.market_cap) else None)
        cap_acc[cap_bucket] = cap_acc.get(cap_bucket, 0.0) + p["value"]

    by_sector = sorted(
        [{"sector": s, "value": v, "pct": round(v / total_value * 100, 1)}
         for s, v in sector_acc.items()],
        key=lambda x: -x["value"],
    )
    by_cap_bucket = sorted(
        [{"bucket": b, "value": v, "pct": round(v / total_value * 100, 1)}
         for b, v in cap_acc.items()],
        key=lambda x: -x["value"],
    )

    # Top 5 + Herfindahl
    by_value = sorted(positions, key=lambda x: -x["value"])
    top_n = [
        {"symbol": p["symbol"], "value": p["value"],
         "pct": round(p["value"] / total_value * 100, 1)}
        for p in by_value[:5]
    ]
    # Herfindahl on weights, scaled 0-10000. >2500 = highly concentrated.
    # Position-level (per-stock weight²) is the strict definition, but for an
    # analyst "concentration" usually means sector. Expose both so the UI can
    # show the analyst-intuitive sector value while keeping the legacy field.
    herf_positions = sum((p["value"] / total_value * 100) ** 2 for p in positions)
    herf_sectors = sum((v / total_value * 100) ** 2 for v in sector_acc.values())

    return {
        "total_value": total_value,
        "position_count": len(positions),
        "by_sector": by_sector,
        "by_cap_bucket": by_cap_bucket,
        "top_n": top_n,
        # Kept for backwards compatibility with any in-flight clients.
        "herfindahl": round(herf_positions, 1),
        "herfindahl_positions": round(herf_positions, 1),
        "herfindahl_sectors": round(herf_sectors, 1),
    }


def _get_authed_kite(user: User) -> KiteConnect:
    if not user.kite_api_key:
        raise HTTPException(status_code=400, detail="Kite API key not configured")
    if not user.kite_access_token:
        raise HTTPException(status_code=400, detail="Not connected to Kite. Login via Settings.")
    kite = KiteConnect(api_key=user.kite_api_key)
    kite.set_access_token(user.kite_access_token)
    return kite


@router.get("/holdings")
async def get_holdings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        holdings = await cached_holdings(user)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Kite API error: {e}")

    # Enrich with company names from fundamentals cache
    from app.services.portfolio_cache import holding_total_qty
    symbols = [h.get("tradingsymbol", "").upper() for h in holdings if holding_total_qty(h) > 0]
    fund_map = await get_cached_fundamentals_bulk(symbols, db) if symbols else {}

    total_invested = 0.0
    total_current = 0.0
    total_prev_close_value = 0.0
    stocks = []

    for h in holdings:
        qty = holding_total_qty(h)
        avg = h.get("average_price", 0)
        ltp = h.get("last_price", 0)
        prev_close = h.get("close_price", 0)

        invested = avg * qty
        current = ltp * qty
        prev_close_value = prev_close * qty
        pnl = current - invested
        pnl_pct = (pnl / invested * 100) if invested else 0
        day_pnl = current - prev_close_value

        total_invested += invested
        total_current += current
        total_prev_close_value += prev_close_value

        sym = h.get("tradingsymbol", "").upper()
        fund = fund_map.get(sym)

        stocks.append({
            "tradingsymbol": h.get("tradingsymbol"),
            "name": fund.name if fund and fund.name else None,
            "exchange": h.get("exchange"),
            "instrument_token": h.get("instrument_token"),
            "quantity": qty,
            "average_price": round(avg, 2),
            "last_price": round(ltp, 2),
            "close_price": round(prev_close, 2),
            "day_change_pct": round(h.get("day_change_percentage", 0), 2),
            "day_pnl": round(day_pnl, 2),
            "invested": round(invested, 2),
            "current_value": round(current, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
        })

    stocks.sort(key=lambda s: s["pnl_pct"])

    total_pnl = total_current - total_invested
    total_pnl_pct = (total_pnl / total_invested * 100) if total_invested else 0
    total_day_pnl = total_current - total_prev_close_value
    total_day_pnl_pct = (total_day_pnl / total_prev_close_value * 100) if total_prev_close_value else 0

    return {
        "total_invested": round(total_invested, 2),
        "total_current": round(total_current, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "total_day_pnl": round(total_day_pnl, 2),
        "total_day_pnl_pct": round(total_day_pnl_pct, 2),
        "stock_count": len(stocks),
        "stocks": stocks,
    }


@router.get("/positions")
async def get_positions(user: User = Depends(get_current_user)) -> dict:
    kite = _get_authed_kite(user)
    try:
        positions = kite.positions()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Kite API error: {e}")
    return positions
