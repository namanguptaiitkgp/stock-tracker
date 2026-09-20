import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.investment_decision import InvestmentDecision
from app.models.user import User
from app.models.watchlist import Watchlist, WatchlistItem, WatchlistJournalEntry
from app.services.investment_decision import evaluate_stock_for_investment

logger = logging.getLogger(__name__)
router = APIRouter()


class EvaluateRequest(BaseModel):
    symbol: str
    exchange: str = "NSE"


@router.post("/evaluate")
async def evaluate_stock(
    body: EvaluateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await evaluate_stock_for_investment(
        symbol=body.symbol,
        exchange=body.exchange,
        user=user,
        db=db,
    )

    # Save to DB
    record = InvestmentDecision(
        user_id=user.id,
        symbol=result["symbol"],
        exchange=result["exchange"],
        verdict=result.get("verdict"),
        confidence=result.get("confidence"),
        model_used=result.get("model_used"),
        strategies_passed=result.get("strategies_passed", 0),
        strategies_total=result.get("strategies_total", 0),
        result_json=result,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    result["id"] = record.id
    result["created_at"] = record.created_at.isoformat() if record.created_at else None

    # Mirror this verdict into the watchlist journal so the Researching card
    # shows that an analysis ran on this symbol. Posts one journal entry per
    # WatchlistItem the user owns that matches the symbol — different
    # watchlists may track the same stock for different reasons, and each
    # journal lives per-item.
    try:
        items_q = (
            select(WatchlistItem)
            .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
            .where(
                Watchlist.user_id == user.id,
                WatchlistItem.symbol == result["symbol"].upper(),
            )
        )
        wl_items = list((await db.execute(items_q)).scalars().all())
        if wl_items:
            verdict = (record.verdict or "n/a").upper()
            confidence = record.confidence
            summary = (
                (result.get("summary") if isinstance(result, dict) else None)
                or (result.get("reasoning") if isinstance(result, dict) else None)
                or ""
            )
            body_text = (
                f"[Analysis · {result['symbol']}] {verdict}"
                + (f" · {int(confidence)}% conf" if confidence is not None else "")
                + (f"\n{summary[:600]}" if summary else "")
            )
            for it in wl_items:
                db.add(WatchlistJournalEntry(
                    watchlist_item_id=it.id,
                    user_id=user.id,
                    body=body_text[:4000],
                ))
            await db.commit()
    except Exception:
        # Journal mirroring is a best-effort side effect — never block the
        # primary verdict response on a journal write failure.
        logger.exception("evaluate→journal mirror failed for %s", result.get("symbol"))

    return result


@router.get("/history")
async def list_decision_history(
    symbol: Optional[str] = None,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    query = (
        select(InvestmentDecision)
        .where(InvestmentDecision.user_id == user.id)
        .order_by(desc(InvestmentDecision.created_at))
        .limit(limit)
    )
    if symbol:
        query = query.where(InvestmentDecision.symbol == symbol.upper().strip())

    result = await db.execute(query)
    decisions = result.scalars().all()

    return [
        {
            "id": d.id,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "symbol": d.symbol,
            "exchange": d.exchange,
            "verdict": d.verdict,
            "confidence": d.confidence,
            "strategies_passed": d.strategies_passed,
            "strategies_total": d.strategies_total,
        }
        for d in decisions
    ]


@router.get("/history/{decision_id}")
async def get_decision_detail(
    decision_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(InvestmentDecision).where(
            InvestmentDecision.id == decision_id,
            InvestmentDecision.user_id == user.id,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Decision not found")

    data = dict(record.result_json)
    data["id"] = record.id
    data["created_at"] = record.created_at.isoformat() if record.created_at else None
    return data


@router.delete("/history/{decision_id}")
async def delete_decision(
    decision_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(InvestmentDecision).where(
            InvestmentDecision.id == decision_id,
            InvestmentDecision.user_id == user.id,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Decision not found")

    await db.delete(record)
    await db.commit()
    return {"status": "deleted", "id": decision_id}


@router.post("/review/{symbol}")
async def mark_reviewed(
    symbol: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(InvestmentDecision)
        .where(
            InvestmentDecision.user_id == user.id,
            InvestmentDecision.symbol == symbol.upper().strip(),
        )
        .order_by(desc(InvestmentDecision.created_at))
        .limit(1)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="No decision found for symbol")
    record.reviewed_at = datetime.now(tz=timezone.utc)
    await db.commit()
    await db.refresh(record)
    return {"symbol": record.symbol, "reviewed_at": record.reviewed_at.isoformat()}


@router.delete("/review/{symbol}")
async def unmark_reviewed(
    symbol: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(InvestmentDecision)
        .where(
            InvestmentDecision.user_id == user.id,
            InvestmentDecision.symbol == symbol.upper().strip(),
        )
        .order_by(desc(InvestmentDecision.created_at))
        .limit(1)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="No decision found for symbol")
    record.reviewed_at = None
    await db.commit()
    return {"symbol": record.symbol, "reviewed_at": None}
