import asyncio
import logging

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.morning_news.run_morning_news_scan_task")
def run_morning_news_scan_task():
    """Celery task: run the morning news scan."""
    logger.info("Starting morning news scan...")

    try:
        asyncio.run(_run_scan())
    except Exception as e:
        logger.error(f"Morning news scan failed: {e}")


async def _run_scan():
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.config import get_settings
    from app.services.news_scraper import run_morning_news_scan
    from app.models.daily_news_report import DailyNewsReport
    from app.models.user import User
    from sqlalchemy import select

    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as db:
        # Get the first user (single-user app)
        result = await db.execute(select(User).limit(1))
        user = result.scalar_one_or_none()
        if not user:
            return

        report = await run_morning_news_scan(user_id=user.id, db=db)

        # Save to DB
        record = DailyNewsReport(
            user_id=user.id,
            report_date=report.get("report_date"),
            total_headlines=report.get("total_headlines", 0),
            companies_found=report.get("companies_found", 0),
            result_json=report,
        )
        db.add(record)
        await db.commit()

    await engine.dispose()
