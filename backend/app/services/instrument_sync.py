import asyncio
import logging

from kiteconnect import KiteConnect
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stock import Stock

logger = logging.getLogger(__name__)


async def sync_instruments(
    kite: KiteConnect,
    db: AsyncSession,
    exchanges: list[str] | None = None,
) -> dict:
    """Download full instrument list from Kite and replace stocks table.
    Uses delete-then-bulk-insert for speed (~5000 rows in <2 seconds)."""

    if exchanges is None:
        exchanges = ["NSE", "BSE"]

    all_instruments = await asyncio.to_thread(kite.instruments)

    equity_types = {"EQ", "BE", "SM", "ST", ""}
    filtered = [
        i for i in all_instruments
        if i.get("exchange") in exchanges
        and i.get("instrument_type", "") in equity_types
        and i.get("segment") in {"NSE", "BSE"}
        and i.get("tradingsymbol")
    ]

    logger.info(f"Fetched {len(all_instruments)} total, {len(filtered)} equity stocks")

    # Delete existing and bulk insert — much faster than per-row upsert
    await db.execute(delete(Stock))

    def _int(val, default=0):
        try:
            return int(val) if val is not None else default
        except (TypeError, ValueError):
            return default

    def _float(val):
        try:
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    batch = []
    for inst in filtered:
        batch.append(Stock(
            instrument_token=_int(inst.get("instrument_token")),
            exchange_token=_int(inst.get("exchange_token")),
            tradingsymbol=str(inst.get("tradingsymbol", "")),
            name=inst.get("name") or None,
            exchange=str(inst.get("exchange", "")),
            segment=inst.get("segment"),
            instrument_type=inst.get("instrument_type"),
            lot_size=_int(inst.get("lot_size"), 1),
            tick_size=_float(inst.get("tick_size")),
            expiry=inst.get("expiry") or None,
            last_price=_float(inst.get("last_price")),
        ))

    db.add_all(batch)
    await db.commit()

    logger.info(f"Instrument sync complete: {len(batch)} stocks inserted")
    return {"added": len(batch), "updated": 0, "total_filtered": len(filtered)}


async def get_stock_count(db: AsyncSession) -> int:
    result = await db.execute(select(func.count(Stock.id)))
    return result.scalar_one()


async def get_last_sync_time(db: AsyncSession) -> str | None:
    result = await db.execute(
        select(Stock.updated_at).order_by(Stock.updated_at.desc()).limit(1)
    )
    row = result.scalar_one_or_none()
    return row.isoformat() if row else None
