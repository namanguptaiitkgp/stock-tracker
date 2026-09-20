"""Morning pipeline: news scan → data refresh → AI analysis.

Three modes:
  full    — all steps (12:00 IST scheduled + manual "Run Now")
  news    — steps 1–3 only (manual "Refresh News")
  refresh — steps 5–7 + brief cache (manual dashboard "Refresh")

Full pipeline steps:
  1. Broad news scan (unified aggregator → classify → DailyNewsReport)
  2. Per-symbol news sentiment (Google News → Gemini)
  3. Sector-level news analysis (deduped by unique sector)
  4. Per-stock card analysis (3 sections: valuation, peers, news+outlook)
  5. Force-refresh fundamentals from yfinance (bypass 24h cache)
  6. Force-refresh Kite holdings + quotes (bypass 2h/60s cache)
  7. Run AI investment evaluation per holding
  8. Recompute and cache the morning brief
"""

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

PIPELINE_SOURCES = ("morning_pipeline", "news_scan", "brief_refresh", "cards_refresh")
STALE_MINUTES = 30


async def get_active_pipeline(db: AsyncSession) -> dict | None:
    """Return info about a currently running pipeline, or None."""
    from app.models.smart_money import IngestionRun

    cutoff = datetime.now(tz=timezone.utc) - timedelta(minutes=STALE_MINUTES)
    row = (await db.execute(
        select(IngestionRun)
        .where(
            IngestionRun.source.in_(PIPELINE_SOURCES),
            IngestionRun.status == "running",
            IngestionRun.started_at > cutoff,
        )
        .order_by(IngestionRun.started_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    if not row:
        return None
    return {
        "source": row.source,
        "task_id": row.celery_task_id,
        "started_at": row.started_at.isoformat() if row.started_at else None,
    }


# ---------------------------------------------------------------------------
# Celery tasks
# ---------------------------------------------------------------------------

@celery_app.task(
    name="app.tasks.morning_pipeline.run_morning_pipeline",
    queue="analysis",
    bind=True,
)
def run_morning_pipeline(self):
    logger.info("=== Morning pipeline (full) started ===")
    try:
        asyncio.run(_run_with_logging(self.request.id, source="morning_pipeline", mode="full"))
    except Exception as e:
        logger.error(f"Morning pipeline failed: {e}", exc_info=True)


@celery_app.task(
    name="app.tasks.morning_pipeline.run_news_scan",
    queue="analysis",
    bind=True,
)
def run_news_scan(self):
    logger.info("=== News scan started ===")
    try:
        asyncio.run(_run_with_logging(self.request.id, source="news_scan", mode="news"))
    except Exception as e:
        logger.error(f"News scan failed: {e}", exc_info=True)


@celery_app.task(
    name="app.tasks.morning_pipeline.run_brief_refresh",
    queue="analysis",
    bind=True,
)
def run_brief_refresh(self):
    logger.info("=== Brief refresh started ===")
    try:
        asyncio.run(_run_with_logging(self.request.id, source="brief_refresh", mode="refresh"))
    except Exception as e:
        logger.error(f"Brief refresh failed: {e}", exc_info=True)


@celery_app.task(
    name="app.tasks.morning_pipeline.run_cards_refresh",
    queue="analysis",
    bind=True,
)
def run_cards_refresh(self):
    """Lightweight: re-runs only the stock-card analysis (valuation +
    peers + news verdict) for all portfolio holdings. Auto-seeds peers
    when missing. Doesn't refresh fundamentals/quotes/news scan/eval —
    use the full pipeline for those."""
    logger.info("=== Cards refresh started ===")
    try:
        asyncio.run(_run_with_logging(self.request.id, source="cards_refresh", mode="cards"))
    except Exception as e:
        logger.error(f"Cards refresh failed: {e}", exc_info=True)


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

_TASK_NAMES = {
    "morning_pipeline": "app.tasks.morning_pipeline.run_morning_pipeline",
    "news_scan": "app.tasks.morning_pipeline.run_news_scan",
    "brief_refresh": "app.tasks.morning_pipeline.run_brief_refresh",
    "cards_refresh": "app.tasks.morning_pipeline.run_cards_refresh",
}


async def _run_with_logging(
    celery_task_id: str | None = None,
    *,
    source: str = "morning_pipeline",
    mode: str = "full",
):
    from app.services.smart_money.run_logger import ingestion_run

    async with ingestion_run(
        source=source,
        task_name=_TASK_NAMES.get(source),
        celery_task_id=celery_task_id,
    ) as ctx:
        await _run_pipeline(ctx, mode=mode)


async def _run_pipeline(ctx=None, *, mode: str = "full"):
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    from app.config import get_settings
    from app.models.user import User
    from app.models.watchlist import Watchlist, WatchlistItem
    from app.models.fundamentals import StockFundamentals

    is_news = mode in ("full", "news")
    is_data = mode in ("full", "refresh")
    is_full = mode == "full"
    is_cards = mode in ("full", "cards")

    total_steps = {"full": 7, "news": 3, "refresh": 3, "cards": 1}[mode]
    step = 0

    def log_step(msg: str):
        nonlocal step
        step += 1
        logger.info(f"Step {step}/{total_steps}: {msg}")
        if ctx:
            ctx.meta["current_step"] = f"{step}/{total_steps}: {msg}"

    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL)
    SM = async_sessionmaker(engine, expire_on_commit=False)

    # Track failures per section
    sentiment_ok = sentiment_fail = 0
    sector_ok = sector_fail = 0
    card_ok = card_fail = 0
    fund_ok = fund_fail = 0
    eval_ok = eval_fail = 0

    async with SM() as db:
        user = (await db.execute(select(User).limit(1))).scalar_one_or_none()
        if not user:
            logger.warning("No user found — aborting pipeline")
            if ctx:
                ctx.meta["skipped"] = "no_user"
            return

        # ── Collect symbols ──────────────────────────────────────────
        portfolio_symbols: set[str] = set()
        if user.kite_api_key:
            try:
                from app.services.portfolio_cache import get_holdings
                holdings = await get_holdings(user, force=bool(user.kite_access_token))
                for h in holdings:
                    qty = (h.get("quantity", 0) or 0) + (h.get("t1_quantity", 0) or 0) + (h.get("collateral_quantity", 0) or 0)
                    if qty > 0:
                        sym = h.get("tradingsymbol", "").upper()
                        if sym:
                            portfolio_symbols.add(sym)
                logger.info(f"Portfolio: {len(portfolio_symbols)} symbols")
            except Exception as e:
                logger.warning(f"Holdings fetch failed: {e}")

        wl_rows = (await db.execute(
            select(Watchlist).where(Watchlist.user_id == user.id)
        )).scalars().all()
        non_system_wl_ids = [w.id for w in wl_rows if not w.is_system]
        all_wl_ids = [w.id for w in wl_rows]

        watchlist_symbols: set[str] = set()
        if non_system_wl_ids:
            items = (await db.execute(
                select(WatchlistItem.symbol).where(WatchlistItem.watchlist_id.in_(non_system_wl_ids))
            )).scalars().all()
            watchlist_symbols = {s.upper() for s in items if s}

        all_wl_symbols: set[str] = set()
        if all_wl_ids:
            items = (await db.execute(
                select(WatchlistItem.symbol).where(WatchlistItem.watchlist_id.in_(all_wl_ids))
            )).scalars().all()
            all_wl_symbols = {s.upper() for s in items if s}

        logger.info(f"Watchlist: {len(watchlist_symbols)} symbols (non-system), {len(all_wl_symbols)} total")

        all_symbols = portfolio_symbols | all_wl_symbols
        if ctx:
            ctx.fetched = len(all_symbols)
            ctx.meta.update(mode=mode, portfolio_symbols=len(portfolio_symbols), watchlist_symbols=len(watchlist_symbols))
        if not all_symbols and not portfolio_symbols:
            logger.info("No symbols to process")
            if is_news:
                logger.info("Running broad scan only")

        # ── News steps (mode=full or mode=news) ─────────────────────
        fund_map: dict[str, StockFundamentals | None] = {}

        if is_news:
            # Step: Broad news scan
            log_step("Running broad news scan...")
            report = None
            try:
                from app.services.news_scraper import run_morning_news_scan
                from app.models.daily_news_report import DailyNewsReport
                from app.observability.activity import ai_purpose

                async with ai_purpose("classify", user_id=user.id):
                    report = await run_morning_news_scan(user_id=user.id, db=db)
                report_date_str = report.get("report_date")
                report_date_val = date.fromisoformat(report_date_str) if report_date_str else date.today()
                record = DailyNewsReport(
                    user_id=user.id,
                    report_date=report_date_val,
                    total_headlines=report.get("total_headlines", 0),
                    companies_found=report.get("companies_found", 0),
                    result_json=report,
                )
                db.add(record)
                await db.commit()
                logger.info(f"  Broad scan done: {report.get('total_headlines', 0)} headlines, {report.get('companies_found', 0)} companies")
            except Exception as e:
                await db.rollback()
                logger.warning(f"  Broad news scan failed (continuing): {e}")

            if ctx:
                ctx.meta["news_headlines"] = report.get("total_headlines", 0) if report else 0

            # ── Auto-onboard unknown stocks tagged by the classifier ──
            # New stocks Gemini flagged in headlines: queue onboarding so
            # by the time the user opens News Scan, fundamentals + peers +
            # relative valuation are ready. Idempotent — known stocks skip.
            if report:
                try:
                    from app.tasks.news_onboarding import onboard_news_stock
                    from app.models.fundamentals import StockFundamentals as _SF

                    tagged_syms = {
                        (c.get("symbol") or "").upper().strip()
                        for c in (report.get("companies") or [])
                        if c.get("symbol")
                    }
                    if tagged_syms:
                        existing_q = await db.execute(
                            select(_SF.symbol).where(_SF.symbol.in_(list(tagged_syms)))
                        )
                        existing_syms = {s for s, in existing_q.all()}
                        new_syms = sorted(tagged_syms - existing_syms)
                        # Cap at 15 to control LLM spend per pipeline cycle.
                        for s in new_syms[:15]:
                            onboard_news_stock.delay(s, user.id)
                        if new_syms:
                            logger.info(f"  Queued onboarding for {len(new_syms[:15])} new symbols (of {len(new_syms)} unknown)")

                        # For ALREADY-known symbols (have fundamentals) tagged
                        # in today's news, fire peer warmup so any without
                        # stored peers get them. Idempotent — no-op when peers
                        # already exist. Covers the "New Opportunities" path.
                        try:
                            from app.tasks.peer_warmup_task import warm_peers_for_symbol
                            from app.models.stock_peers import StockPeer
                            already_peered_q = await db.execute(
                                select(StockPeer.symbol).where(
                                    StockPeer.symbol.in_(list(existing_syms))
                                )
                            )
                            already_peered = {s for s, in already_peered_q.all()}
                            missing_peers = sorted(existing_syms - already_peered)
                            for s in missing_peers[:15]:
                                warm_peers_for_symbol.delay(s, user.id)
                            if missing_peers:
                                logger.info(
                                    f"  Queued peer warmup for {len(missing_peers[:15])} "
                                    f"tagged symbols missing peers (of {len(missing_peers)})"
                                )
                        except Exception as e:
                            logger.warning(f"  Peer warmup dispatch failed: {e}")
                except Exception as e:
                    logger.warning(f"  News-onboarding dispatch failed: {e}")

            if not all_symbols:
                logger.info("No symbols to process — skipping per-symbol steps")
                await engine.dispose()
                return

            # Build fund_map for sentiment + sector steps
            if all_symbols:
                result = await db.execute(
                    select(StockFundamentals).where(StockFundamentals.symbol.in_(list(all_symbols)))
                )
                fund_map = {f.symbol: f for f in result.scalars().all()}

            # Step: Per-symbol news sentiment — iterate only symbols tagged
            # by today's news scan OR with stale sentiment cache (>3 days).
            # Stocks not mentioned in any headline today keep yesterday's
            # sentiment — cuts ~80% of Gemini sentiment calls.
            from app.services.news_sentiment import get_news_sentiment
            from app.models.news_sentiment import NewsSentimentCache
            from app.models.daily_news_report import DailyNewsReport
            from sqlalchemy import desc

            today_ist = date.today()
            async with SM() as t_db:
                tagged_rows = (await t_db.execute(
                    select(DailyNewsReport)
                    .where(DailyNewsReport.user_id == user.id)
                    .where(DailyNewsReport.report_date == today_ist)
                    .order_by(desc(DailyNewsReport.id))
                    .limit(1)
                )).scalars().all()
                tagged_today: set[str] = set()
                for r in tagged_rows:
                    for c in (r.result_json or {}).get("companies", []) or []:
                        s = (c.get("symbol") or "").upper().strip()
                        if s:
                            tagged_today.add(s)

                # Also include symbols with stale or missing sentiment cache.
                cache_rows = (await t_db.execute(
                    select(NewsSentimentCache.symbol, NewsSentimentCache.analyzed_at)
                    .where(NewsSentimentCache.symbol.in_(list(all_symbols)))
                )).all()
                latest_by_sym: dict[str, datetime] = {}
                for sym_col, ts in cache_rows:
                    if sym_col not in latest_by_sym or (ts and ts > latest_by_sym[sym_col]):
                        latest_by_sym[sym_col] = ts

            now_utc = datetime.now(timezone.utc)
            stale_cutoff = now_utc - timedelta(days=3)
            sentiment_targets: list[str] = []
            sentiment_skipped = 0
            for sym in sorted(all_symbols):
                if sym in tagged_today:
                    sentiment_targets.append(sym)
                    continue
                last = latest_by_sym.get(sym)
                if last is None or last < stale_cutoff:
                    sentiment_targets.append(sym)
                    continue
                sentiment_skipped += 1

            log_step(
                f"Refreshing news sentiment for {len(sentiment_targets)}/{len(all_symbols)} "
                f"(tagged-today {len(tagged_today)}, fresh-skipped {sentiment_skipped})..."
            )

            sem = asyncio.Semaphore(5)

            from app.observability.activity import ai_purpose

            async def _refresh_sentiment(sym: str):
                nonlocal sentiment_ok, sentiment_fail
                async with sem:
                    try:
                        name = fund_map[sym].name if fund_map.get(sym) and fund_map[sym].name else None
                        async with SM() as s_db, ai_purpose("sentiment", symbol=sym, user_id=user.id):
                            sentiment = await get_news_sentiment(sym, name, days=7, user_id=user.id, db=s_db)
                            s_db.add(NewsSentimentCache(
                                symbol=sym,
                                sentiment=sentiment.get("sentiment"),
                                score=sentiment.get("score"),
                                result_json=sentiment,
                                analyzed_at=datetime.now(timezone.utc),
                            ))
                            await s_db.commit()
                        sentiment_ok += 1
                    except Exception as e:
                        sentiment_fail += 1
                        logger.warning(f"  Sentiment failed for {sym}: {e}")

            await asyncio.gather(*[_refresh_sentiment(s) for s in sentiment_targets])
            logger.info(
                f"  Sentiment done: {sentiment_ok} ok, {sentiment_fail} failed, "
                f"{sentiment_skipped} skipped (no fresh news)"
            )
            if ctx:
                ctx.meta.update(sentiment_ok=sentiment_ok, sentiment_fail=sentiment_fail)

            # Step: Sector-level news analysis (canonical 11 every day).
            # Previously this iterated over `unique_sectors` derived from
            # the user's portfolio + watchlist via `resolve_sectors_bulk`.
            # That meant sectors with no held/watched stocks (e.g. Energy,
            # Real Estate for users who own zero PSU oil/realty names)
            # never got refreshed and never appeared in Market Brief.
            # Now we always refresh the project's canonical sector taxonomy
            # (`CANONICAL_SECTORS` — 11 GICS-style names defined in
            # `screener_presets.py`) so Market Brief gives a complete
            # macro picture, not just the user's pocket. Cost delta is
            # ~3 extra Gemini Flash-Lite calls per pipeline run, bounded
            # by the existing Semaphore(3) below.
            from app.services.screener_presets import CANONICAL_SECTORS
            from app.services.sector_news import refresh_sector_analysis

            unique_sectors = set(CANONICAL_SECTORS)
            log_step(f"Running sector analysis for {len(unique_sectors)} sectors (canonical)...")

            sector_sem = asyncio.Semaphore(3)

            async def _refresh_sector(sector_name: str):
                nonlocal sector_ok, sector_fail
                async with sector_sem:
                    try:
                        async with SM() as sec_db, ai_purpose("sector_news", user_id=user.id):
                            await refresh_sector_analysis(sector_name, sec_db, user.id)
                        sector_ok += 1
                    except Exception as e:
                        sector_fail += 1
                        logger.warning(f"  Sector analysis failed for {sector_name}: {e}")

            await asyncio.gather(*[_refresh_sector(s) for s in sorted(unique_sectors)])
            logger.info(f"  Sector analysis done: {sector_ok} ok, {sector_fail} failed")
            if ctx:
                ctx.meta.update(sector_ok=sector_ok, sector_fail=sector_fail)

        # ── Stock card analysis (mode=full or mode=cards) ────────────
        if is_cards and portfolio_symbols:
            log_step(f"Running stock card analysis for {len(portfolio_symbols)} holdings...")
            from app.services.stock_card import refresh_stock_analysis

            card_sem = asyncio.Semaphore(5)

            async def _refresh_card(sym: str):
                nonlocal card_ok, card_fail
                async with card_sem:
                    try:
                        async with SM() as c_db, ai_purpose("card_analysis", symbol=sym, user_id=user.id):
                            await refresh_stock_analysis(sym, c_db, user.id)
                        card_ok += 1
                    except Exception as e:
                        card_fail += 1
                        logger.warning(f"  Stock card failed for {sym}: {e}")

            await asyncio.gather(*[_refresh_card(s) for s in sorted(portfolio_symbols)])
            logger.info(f"  Stock card done: {card_ok} ok, {card_fail} failed")
            if ctx:
                ctx.meta.update(card_ok=card_ok, card_fail=card_fail)

        # ── Data refresh steps (mode=full or mode=refresh) ───────────
        if is_data:
            if not all_symbols:
                logger.info("No symbols to process — skipping data steps")
                await engine.dispose()
                return

            # Step: Refresh fundamentals — weekly + event-driven
            # Fundamentals don't change daily; quarterly filings + material
            # corp actions are the real triggers. Skip stocks last fetched
            # within FRESHNESS_HOURS_AUTO (7d), unless a material corp ann
            # has dropped in the meantime.
            #
            # Symbol set expansion (Phase G1): include peers of holdings so
            # peer-comparison verdicts compute against fresh peer data.
            from app.services.fundamentals_service import (
                get_fundamentals,
                get_cached_fundamentals_bulk,
                FRESHNESS_HOURS_AUTO,
                _symbols_with_recent_material_announcement,
            )
            from app.models.stock_peers import StockPeer as _SP

            peer_extras: set[str] = set()
            if portfolio_symbols:
                async with SM() as p_db:
                    peer_q = await p_db.execute(
                        select(_SP.peer_symbol).where(
                            _SP.symbol.in_(list(portfolio_symbols))
                        )
                    )
                    for (sym,) in peer_q.all():
                        if sym and sym not in all_symbols:
                            peer_extras.add(sym)

            sorted_syms = sorted(all_symbols | peer_extras)
            logger.info(
                f"  Fundamentals scope: {len(all_symbols)} holdings+watchlist "
                f"+ {len(peer_extras)} peers-of-holdings = {len(sorted_syms)} total"
            )
            async with SM() as gate_db:
                cached_map = await get_cached_fundamentals_bulk(sorted_syms, gate_db)
                event_force = await _symbols_with_recent_material_announcement(
                    gate_db, sorted_syms, days=7,
                )

            from datetime import timedelta as _td
            now_utc = datetime.now(timezone.utc)
            stale_threshold = _td(hours=FRESHNESS_HOURS_AUTO)
            symbols_to_refresh: list[str] = []
            fund_fresh_skipped = 0
            for sym in sorted_syms:
                if sym in event_force:
                    symbols_to_refresh.append(sym)
                    continue
                cached = cached_map.get(sym)
                if cached and cached.fetched_at and (now_utc - cached.fetched_at) < stale_threshold:
                    fund_fresh_skipped += 1
                    continue
                symbols_to_refresh.append(sym)

            log_step(
                f"Refreshing fundamentals for {len(symbols_to_refresh)}/{len(sorted_syms)} symbols "
                f"(event-forced {len(event_force)}, fresh-skipped {fund_fresh_skipped})..."
            )
            fund_sem = asyncio.Semaphore(10)

            async def _refresh_fund(sym: str):
                nonlocal fund_ok, fund_fail
                async with fund_sem:
                    try:
                        async with SM() as f_db:
                            await get_fundamentals(sym, f_db, force_refresh=True, user_id=user.id)
                        fund_ok += 1
                    except Exception as e:
                        fund_fail += 1
                        logger.warning(f"  Fundamentals failed for {sym}: {e}")

            await asyncio.gather(*[_refresh_fund(s) for s in symbols_to_refresh])
            logger.info(
                f"  Fundamentals done: {fund_ok} ok, {fund_fail} failed, "
                f"{fund_fresh_skipped} skipped (fresh)"
            )
            if ctx:
                ctx.meta.update(fund_ok=fund_ok, fund_fail=fund_fail)

            # Stage 3a (additive): also kick off a metric_snapshots refresh
            # for the same scope so the "Snapshot" chip on the stock-detail
            # page stays fresh. Fire-and-forget — runs in parallel to the
            # rest of this pipeline in its own worker slot (queue="analysis").
            # See app/tasks/metric_snapshot_task.py.
            try:
                celery_app.send_task(
                    "app.tasks.metric_snapshot.refresh_portfolio_snapshots",
                    queue="analysis",
                )
                logger.info("  Dispatched portfolio metric_snapshots refresh task")
            except Exception as e:
                logger.warning(f"  Failed to dispatch metric_snapshots refresh: {e}")

            # Step: Force-refresh Kite quotes
            if user.kite_api_key and user.kite_access_token:
                log_step("Refreshing Kite quotes...")
                try:
                    from app.services.portfolio_cache import get_quote
                    kite_syms = [f"NSE:{s}" for s in sorted(all_symbols)]
                    batch_size = 50
                    for i in range(0, len(kite_syms), batch_size):
                        batch = kite_syms[i : i + batch_size]
                        await get_quote(user, batch, force=True)
                    logger.info(f"  Kite quotes refreshed for {len(kite_syms)} symbols")
                except Exception as e:
                    logger.warning(f"  Kite quote refresh failed (continuing): {e}")
            else:
                log_step("Skipped Kite quotes (not connected)")

            # Step: AI investment evaluation — event-driven (parallel)
            # Skip holdings whose verdict was set recently AND none of the
            # trigger conditions fired (news swing, corp ann, smart-money
            # update, 7-day fallback). Drastically cuts daily Gemini spend.
            from app.services.investment_decision import evaluate_stock_for_investment
            from app.models.investment_decision import InvestmentDecision
            from app.services.eval_dispatcher import should_reevaluate

            eval_targets: list[str] = []
            eval_skipped = 0
            async with SM() as g_db:
                for sym in sorted(portfolio_symbols):
                    do_eval, reason = await should_reevaluate(sym, g_db, user.id)
                    if do_eval:
                        eval_targets.append(sym)
                    else:
                        eval_skipped += 1
                        logger.info(f"  Eval skipped {sym}: {reason}")

            log_step(
                f"Running AI evaluation on {len(eval_targets)}/{len(portfolio_symbols)} holdings "
                f"(skipped {eval_skipped} for no_change)..."
            )

            eval_sem = asyncio.Semaphore(5)

            async def _evaluate_one(sym: str) -> None:
                nonlocal eval_ok, eval_fail
                async with eval_sem:
                    try:
                        async with SM() as e_db, ai_purpose("investment_eval", symbol=sym, user_id=user.id):
                            evaluation = await evaluate_stock_for_investment(
                                symbol=sym, exchange="NSE", user=user, db=e_db,
                            )
                            e_db.add(InvestmentDecision(
                                user_id=user.id,
                                symbol=sym,
                                exchange="NSE",
                                verdict=evaluation.get("verdict"),
                                confidence=evaluation.get("confidence"),
                                model_used=evaluation.get("model_used", ""),
                                strategies_passed=evaluation.get("strategies_passed", 0),
                                strategies_total=evaluation.get("strategies_total", 0),
                                result_json=evaluation,
                            ))
                            await e_db.commit()
                        eval_ok += 1
                        logger.info(f"  {sym}: {evaluation.get('verdict')} ({evaluation.get('confidence')}%)")
                    except Exception as e:
                        eval_fail += 1
                        logger.warning(f"  {sym}: evaluation failed — {e}")

            await asyncio.gather(*[_evaluate_one(s) for s in eval_targets])
            logger.info(
                f"  Evaluation done: {eval_ok} ok, {eval_fail} failed, "
                f"{eval_skipped} skipped (no_change)"
            )
            if ctx:
                ctx.inserted = eval_ok
                ctx.meta.update(eval_ok=eval_ok, eval_fail=eval_fail)

        # ── Failure tracking ─────────────────────────────────────────
        if ctx:
            failures = []
            if sentiment_fail:
                failures.append(f"{sentiment_fail} sentiment failures")
            if sector_fail:
                failures.append(f"{sector_fail} sector analysis failures")
            if card_fail:
                failures.append(f"{card_fail} stock card failures")
            if fund_fail:
                failures.append(f"{fund_fail} fundamentals failures")
            if eval_fail:
                failures.append(f"{eval_fail} evaluation failures")
            if failures:
                ctx.mark_partial(", ".join(failures))

        # ── Recompute brief cache (full + refresh modes) ─────────────
        if is_data:
            logger.info("Refreshing brief cache...")
            try:
                from app.api.today import _compute_brief, _persist_cache
                import time
                async with SM() as b_db:
                    started = time.monotonic()
                    payload = await _compute_brief(user, b_db, force_kite=True)
                    compute_ms = int((time.monotonic() - started) * 1000)
                    await _persist_cache(b_db, user.id, payload, compute_ms, datetime.now(tz=timezone.utc))
                logger.info(f"  Brief cache refreshed ({compute_ms} ms)")
            except Exception as e:
                logger.warning(f"  Brief cache refresh failed: {e}")

    await engine.dispose()
    logger.info(f"=== Pipeline ({mode}) complete ===")
