"""Daily review-alert evaluator task.

Runs ~10 minutes after `watchlist_snapshots.snapshot_watchlist_valuations`
so the freshly-written WatchlistValuationSnapshot rows are available for
rule evaluation. Iterates over every user that owns at least one
watchlist and calls the existing `evaluate_alerts_for_user` —
no new evaluation logic, just a scheduled fan-out.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.db.session import async_session
from app.models.user import User
from app.models.watchlist import Watchlist
from app.services.review_alerts import evaluate_alerts_for_user
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _run(celery_task_id: str | None = None) -> dict:
    from app.services.smart_money.run_logger import ingestion_run

    async with ingestion_run(
        source="review_alerts",
        task_name="app.tasks.review_alerts.run_review_alerts_eval",
        celery_task_id=celery_task_id,
    ) as ctx:
        async with async_session() as db:
            owner_subq = select(Watchlist.user_id).distinct()
            res = await db.execute(select(User).where(User.id.in_(owner_subq)))
            users = list(res.scalars().all())

            total = 0
            for user in users:
                try:
                    total += await evaluate_alerts_for_user(user, db)
                except Exception:
                    logger.exception(
                        "review-alerts eval failed for user_id=%s", user.id
                    )
            logger.info(
                "review-alerts beat: users=%d alerts_created=%d", len(users), total
            )
            ctx.fetched = len(users)
            ctx.inserted = total
            return {"users": len(users), "alerts_created": total}


@celery_app.task(name="app.tasks.review_alerts.run_review_alerts_eval", bind=True)
def run_review_alerts_eval(self) -> dict:
    return asyncio.run(_run(celery_task_id=self.request.id))
