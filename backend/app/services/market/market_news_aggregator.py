"""Aggregate market-wide news — thin wrapper around the unified news aggregator.

Historically this module had its own RSS fetch logic (Hindu BL + Moneycontrol +
ET + Google News).  Now it delegates to ``news.inbox_aggregator.fetch_all_news``
so all consumers share a single cache and a single set of sources.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def fetch_market_news(days: int = 1, cap: int = 50) -> list[dict]:
    """Backwards-compatible entry point used by ``news_scraper.run_morning_news_scan``
    and ``MarketPulse``.  Delegates to the unified aggregator.
    """
    from app.services.news.inbox_aggregator import fetch_all_news
    return await fetch_all_news(days=days, cap=cap)
