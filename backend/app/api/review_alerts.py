"""Review alerts API.

Endpoints:
  GET    /api/review-alerts                 list user's alerts
  GET    /api/review-alerts/count            lightweight count
  POST   /api/review-alerts/{id}/apply       confirm + apply (mandatory dialog)
  POST   /api/review-alerts/{id}/dismiss
  POST   /api/review-alerts/evaluate         force-run evaluator + cleanup
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.review_alert import ReviewAlert
from app.models.user import User
from app.models.watchlist import (
    Watchlist,
    WatchlistItem,
    WatchlistJournalEntry,
)
from app.services.review_alerts import (
    cleanup_stale_alerts_for_user,
    evaluate_alerts_for_user,
)

router = APIRouter()


def _serialize(a: ReviewAlert) -> dict:
    return {
        "id": a.id,
        "symbol": a.symbol,
        "exchange": a.exchange,
        "source": a.source,
        "trigger_type": a.trigger_type,
        "trigger_label": a.trigger_label,
        "suggested_action": a.suggested_action,
        "suggested_lane": a.suggested_lane,
        "payload": a.payload or {},
        "status": a.status,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
    }


@router.get("")
@router.get("/")
async def list_alerts(
    status: str = "pending",
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    statuses = ("pending", "applied", "dismissed")
    q = select(ReviewAlert).where(ReviewAlert.user_id == user.id)
    if status != "all":
        if status not in statuses:
            raise HTTPException(status_code=400, detail=f"Invalid status; must be one of {statuses + ('all',)}")
        q = q.where(ReviewAlert.status == status)
    q = q.order_by(desc(ReviewAlert.created_at)).limit(max(1, min(limit, 200)))
    rows = (await db.execute(q)).scalars().all()
    items = [_serialize(a) for a in rows]

    # also compute counts by status for the badge
    counts: dict[str, int] = {"pending": 0, "applied": 0, "dismissed": 0}
    by_source: dict[str, int] = {"watchlist": 0, "holding": 0, "both": 0}
    res = await db.execute(
        select(ReviewAlert.status, ReviewAlert.source)
        .where(ReviewAlert.user_id == user.id)
    )
    for st, src in res.all():
        counts[st] = counts.get(st, 0) + 1
        if st == "pending":
            by_source[src] = by_source.get(src, 0) + 1
    return {
        "items": items,
        "pending_count": counts.get("pending", 0),
        "applied_count": counts.get("applied", 0),
        "dismissed_count": counts.get("dismissed", 0),
        "by_source": by_source,
    }


@router.get("/count")
async def count_alerts(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    res = await db.execute(
        select(ReviewAlert.source)
        .where(ReviewAlert.user_id == user.id, ReviewAlert.status == "pending")
    )
    by_source = {"watchlist": 0, "holding": 0, "both": 0}
    pending = 0
    for (src,) in res.all():
        pending += 1
        by_source[src] = by_source.get(src, 0) + 1
    return {"pending": pending, "by_source": by_source}


class ApplyBody(BaseModel):
    confirm: bool
    lane: Optional[str] = None


@router.post("/{alert_id}/apply")
async def apply_alert(
    alert_id: int,
    body: ApplyBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required (`confirm: true`)")
    res = await db.execute(
        select(ReviewAlert).where(ReviewAlert.id == alert_id, ReviewAlert.user_id == user.id)
    )
    alert = res.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    if alert.status != "pending":
        raise HTTPException(status_code=400, detail=f"Alert is {alert.status}; only pending alerts can be applied")

    target_lane = body.lane or alert.suggested_lane
    journal_msg = None

    # Update watchlist item lane if symbol is in a watchlist
    if alert.source in ("watchlist", "both"):
        wl_res = await db.execute(
            select(WatchlistItem)
            .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
            .where(Watchlist.user_id == user.id, WatchlistItem.symbol == alert.symbol)
        )
        wl_item = wl_res.scalar_one_or_none()
        if wl_item and target_lane:
            prev_lane = wl_item.lane or "researching"
            wl_item.lane = target_lane
            journal_msg = f"Reviewed — {alert.trigger_label} → moved {prev_lane} → {target_lane}"
        elif wl_item:
            journal_msg = f"Reviewed — {alert.trigger_label} (no lane change)"

        if wl_item and journal_msg:
            db.add(WatchlistJournalEntry(
                watchlist_item_id=wl_item.id, body=journal_msg[:4000], user_id=user.id,
            ))

    alert.status = "applied"
    alert.resolved_at = datetime.now(tz=timezone.utc)
    await db.commit()
    return {"ok": True, "id": alert.id, "lane": target_lane, "journal_added": journal_msg is not None}


class DismissBody(BaseModel):
    note: Optional[str] = None


@router.post("/{alert_id}/dismiss")
async def dismiss_alert(
    alert_id: int,
    body: DismissBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    res = await db.execute(
        select(ReviewAlert).where(ReviewAlert.id == alert_id, ReviewAlert.user_id == user.id)
    )
    alert = res.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    if alert.status != "pending":
        raise HTTPException(status_code=400, detail=f"Alert is {alert.status}")
    alert.status = "dismissed"
    alert.resolved_at = datetime.now(tz=timezone.utc)
    if body.note:
        alert.payload = {**(alert.payload or {}), "dismiss_note": body.note[:200]}

    # Auto-journal for watchlist alerts
    if alert.source in ("watchlist", "both"):
        wl_res = await db.execute(
            select(WatchlistItem)
            .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
            .where(Watchlist.user_id == user.id, WatchlistItem.symbol == alert.symbol)
        )
        wl_item = wl_res.scalar_one_or_none()
        if wl_item:
            note_suffix = f" ({body.note})" if body.note else ""
            db.add(WatchlistJournalEntry(
                watchlist_item_id=wl_item.id,
                body=f"Dismissed alert — {alert.trigger_label}{note_suffix}"[:4000],
                user_id=user.id,
            ))
    await db.commit()
    return {"ok": True, "id": alert.id}


@router.post("/evaluate")
async def evaluate_now(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Force-run cleanup + evaluator for the current user."""
    dismissed = await cleanup_stale_alerts_for_user(user, db)
    created = await evaluate_alerts_for_user(user, db)
    return {"dismissed": dismissed, "created": created}
