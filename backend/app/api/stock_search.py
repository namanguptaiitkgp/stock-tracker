import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from kiteconnect import KiteConnect
from sqlalchemy import desc, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.news_sentiment import NewsSentimentCache
from app.models.smart_money import BhavcopyDaily, BulkBlockDeal, SmartMoneySignal
from app.models.stock import Stock
from app.models.user import User
from app.services.instrument_sync import sync_instruments, get_stock_count, get_last_sync_time

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/search")
async def search_stocks(
    q: str = Query(..., min_length=1, description="Search by ticker or company name"),
    exchange: str | None = None,
    limit: int = 20,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Search stocks by tradingsymbol or name with fuzzy matching."""
    q = q.strip()
    q_upper = q.upper()
    q_lower = q.lower()

    # 1. Exact ticker match (highest priority)
    exact = await db.execute(
        select(Stock).where(
            Stock.tradingsymbol == q_upper,
            Stock.segment.in_(["NSE", "BSE"]),
        ).limit(1)
    )
    exact_match = exact.scalar_one_or_none()

    # 2. Prefix match on ticker (e.g., "REL" → RELIANCE, RELAXO, ...)
    prefix_result = await db.execute(
        select(Stock).where(
            Stock.tradingsymbol.ilike(f"{q_upper}%"),
            Stock.segment.in_(["NSE", "BSE"]),
            *([] if exchange is None else [Stock.exchange == exchange]),
        ).order_by(Stock.tradingsymbol).limit(limit)
    )
    prefix_matches = prefix_result.scalars().all()

    # 3. Contains match on ticker (e.g., "BANK" → HDFCBANK, ICICIBANK, ...)
    contains_result = await db.execute(
        select(Stock).where(
            Stock.tradingsymbol.ilike(f"%{q_upper}%"),
            Stock.segment.in_(["NSE", "BSE"]),
            *([] if exchange is None else [Stock.exchange == exchange]),
        ).order_by(Stock.tradingsymbol).limit(limit * 2)
    )
    contains_matches = contains_result.scalars().all()

    # 4. Name search (e.g., "Reliance Industries" or "HDFC")
    name_result = await db.execute(
        select(Stock).where(
            Stock.name.ilike(f"%{q}%"),
            Stock.segment.in_(["NSE", "BSE"]),
            *([] if exchange is None else [Stock.exchange == exchange]),
        ).order_by(Stock.name).limit(limit * 2)
    )
    name_matches = name_result.scalars().all()

    # Merge results: exact → prefix → name → contains, deduplicated
    seen = set()
    results = []

    def add(stock: Stock, match_type: str):
        key = (stock.tradingsymbol, stock.exchange)
        if key in seen:
            return
        seen.add(key)
        results.append({
            "tradingsymbol": stock.tradingsymbol,
            "name": stock.name,
            "exchange": stock.exchange,
            "instrument_token": stock.instrument_token,
            "instrument_type": stock.instrument_type,
            "match_type": match_type,
        })

    if exact_match:
        add(exact_match, "exact")

    for s in prefix_matches:
        add(s, "prefix")

    for s in name_matches:
        add(s, "name")

    for s in contains_matches:
        add(s, "contains")

    # Prefer NSE over BSE when both exist for same symbol
    nse_symbols = {r["tradingsymbol"] for r in results if r["exchange"] == "NSE"}
    results = [r for r in results if not (r["exchange"] == "BSE" and r["tradingsymbol"] in nse_symbols)]

    return results[:limit]


@router.get("/info")
async def stock_info(
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    count = await get_stock_count(db)
    last_sync = await get_last_sync_time(db)
    return {"stock_count": count, "last_sync": last_sync}


@router.post("/sync")
async def trigger_sync(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not user.kite_api_key or not user.kite_access_token:
        raise HTTPException(status_code=400, detail="Kite not connected. Login first.")

    kite = KiteConnect(api_key=user.kite_api_key)
    kite.set_access_token(user.kite_access_token)

    result = await sync_instruments(kite, db)
    return result


@router.post("/{symbol}/refresh-all-sources")
async def refresh_stock_data(
    symbol: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Force re-fetch fundamentals from all sources for a single stock."""
    from app.services.fundamentals_service import get_fundamentals, serialize

    result = await get_fundamentals(symbol.upper().strip(), db, force_refresh=True, user_id=user.id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Could not fetch data for {symbol}")

    return {
        "status": "refreshed",
        "fundamentals": serialize(result),
    }


def _safe_float(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


@router.post("/{symbol}/analyze")
async def analyze_stock(
    symbol: str,
    exchange: str = Query("NSE"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run a comprehensive analysis: fundamentals + news + MF + smart money + AI verdict."""
    from app.models.fundamentals import StockFundamentals
    from app.models.investment_decision import InvestmentDecision
    from app.services.fundamentals_service import get_fundamentals, serialize
    from app.services.investment_decision import evaluate_stock_for_investment
    from app.services.mf_activity import get_mf_activity, get_mf_buysell
    from app.services.news_sentiment import get_news_sentiment

    symbol = symbol.upper().strip()
    errors: dict[str, str] = {}

    # Phase 1: fundamentals first (needed by sentiment + verdict)
    fund = None
    fund_data: dict = {}
    try:
        fund = await get_fundamentals(symbol, db, force_refresh=True, user_id=user.id)
        if fund:
            fund_data = serialize(fund)
    except Exception as e:
        logger.warning(f"analyze: fundamentals failed for {symbol}: {e}")
        errors["fundamentals"] = str(e)[:200]

    company_name = fund.name if fund else None

    # Phase 2: everything else in parallel
    async def fetch_sentiment():
        try:
            cached = await db.execute(
                select(NewsSentimentCache)
                .where(NewsSentimentCache.symbol == symbol)
                .order_by(desc(NewsSentimentCache.analyzed_at))
                .limit(1)
            )
            record = cached.scalar_one_or_none()
            if record and record.analyzed_at:
                age = datetime.now(timezone.utc) - record.analyzed_at
                if age < timedelta(hours=4):
                    return record.result_json

            result = await get_news_sentiment(symbol, company_name, days=7, user_id=user.id, db=db)
            db.add(NewsSentimentCache(
                symbol=symbol,
                sentiment=result.get("sentiment"),
                score=result.get("score"),
                result_json=result,
                analyzed_at=datetime.now(timezone.utc),
            ))
            await db.flush()
            return result
        except Exception as e:
            logger.warning(f"analyze: sentiment failed for {symbol}: {e}")
            errors["news_sentiment"] = str(e)[:200]
            return None

    async def fetch_mf_activity():
        try:
            return await get_mf_activity(symbol)
        except Exception as e:
            logger.warning(f"analyze: MF activity failed for {symbol}: {e}")
            errors["mf_activity"] = str(e)[:200]
            return None

    async def fetch_mf_buysell():
        try:
            return await get_mf_buysell(symbol, company_name)
        except Exception as e:
            logger.warning(f"analyze: MF buysell failed for {symbol}: {e}")
            errors["mf_buysell"] = str(e)[:200]
            return None

    async def fetch_shareholding():
        try:
            from app.services.smart_money.shareholding_pattern import (
                _fetch_nse_shareholding, _persist_with_deltas, REQUEST_TIMEOUT,
            )
            from app.services.smart_money.insider_disclosures import HEADERS as NSE_HEADERS
            import httpx

            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT, headers=NSE_HEADERS, follow_redirects=True,
            ) as client:
                try:
                    await client.get("https://www.nseindia.com", timeout=15)
                except Exception:
                    pass
                row = await _fetch_nse_shareholding(symbol, None, client)

            if row:
                await _persist_with_deltas([row])
                return row
        except Exception as e:
            logger.warning(f"analyze: shareholding refresh failed for {symbol}: {e}")
            errors["shareholding"] = str(e)[:200]
        return None

    async def fetch_smart_money():
        try:
            sig_q = await db.execute(
                select(SmartMoneySignal)
                .where(SmartMoneySignal.symbol == symbol)
                .order_by(desc(SmartMoneySignal.as_of))
                .limit(1)
            )
            sig = sig_q.scalar_one_or_none()

            since = datetime.now().date() - timedelta(days=30)
            deals_q = await db.execute(
                select(BulkBlockDeal)
                .where(BulkBlockDeal.symbol == symbol, BulkBlockDeal.trade_date >= since)
                .order_by(desc(BulkBlockDeal.trade_date))
            )
            deals = deals_q.scalars().all()

            bhav_since = datetime.now().date() - timedelta(days=60)
            bhav_q = await db.execute(
                select(BhavcopyDaily)
                .where(BhavcopyDaily.symbol == symbol, BhavcopyDaily.trade_date >= bhav_since)
                .order_by(BhavcopyDaily.trade_date)
            )
            delivery = bhav_q.scalars().all()

            return {
                "signal": {
                    "composite": _safe_float(sig.composite),
                    "mf_score": _safe_float(sig.mf_score),
                    "deals_score": _safe_float(sig.deals_score),
                    "delivery_score": _safe_float(sig.delivery_score),
                    "as_of": sig.as_of.isoformat(),
                    "named_sharks": sig.named_sharks,
                } if sig else None,
                "deals_count": len(deals),
                "delivery_days": len(delivery),
            }
        except Exception as e:
            logger.warning(f"analyze: smart money failed for {symbol}: {e}")
            errors["smart_money"] = str(e)[:200]
            return None

    async def fetch_verdict():
        try:
            result = await evaluate_stock_for_investment(symbol, exchange, user, db)
            record = InvestmentDecision(
                user_id=user.id,
                symbol=symbol,
                exchange=exchange,
                verdict=result.get("verdict"),
                confidence=result.get("confidence"),
                model_used=result.get("model_used"),
                strategies_passed=result.get("strategies_passed", 0),
                strategies_total=result.get("strategies_total", 0),
                result_json=result,
            )
            db.add(record)
            await db.flush()
            return result
        except Exception as e:
            logger.warning(f"analyze: verdict failed for {symbol}: {e}")
            errors["investment_decision"] = str(e)[:200]
            return None

    # Phase 2a: fetch shareholding + sentiment + MF in parallel
    # Shareholding must complete before verdict so the AI sees fresh ownership data
    sentiment, mf_act, mf_bs, shareholding, sm = await asyncio.gather(
        fetch_sentiment(),
        fetch_mf_activity(),
        fetch_mf_buysell(),
        fetch_shareholding(),
        fetch_smart_money(),
    )

    # Update fundamentals with fresh shareholding data
    if shareholding and fund:
        if shareholding.get("promoter_pct") is not None:
            fund.promoter_holding = shareholding["promoter_pct"]
            fund_data["promoter_holding"] = float(shareholding["promoter_pct"])

    # Phase 2b: verdict runs after shareholding is persisted
    verdict = await fetch_verdict()

    # Phase 2c: stock_card analysis (valuation/peer/news verdicts).
    # Run sequentially after verdict — refresh_stock_analysis internally
    # uses asyncio.gather over evaluate_valuation/evaluate_peers/evaluate_news
    # on the same session, so we can't safely run it in parallel with
    # fetch_verdict on a shared session. The user accepted the latency
    # tradeoff to get the dashboard verdict cards updated in one call.
    stock_card_data: dict | None = None
    try:
        from app.services.stock_card import refresh_stock_analysis
        sa = await refresh_stock_analysis(symbol, db, user.id)
        if sa is not None:
            stock_card_data = {
                "valuation_section": {
                    "verdict": sa.valuation_verdict,
                    "score": float(sa.valuation_score) if sa.valuation_score is not None else None,
                    "signals": sa.valuation_signals,
                    "hard_failed": sa.valuation_hard_failed,
                    "last_run_at": sa.valuation_last_run_at.isoformat() if sa.valuation_last_run_at else None,
                },
                "peer_section": {
                    "verdict": sa.peer_verdict,
                    "metric_breakdown": sa.peer_metric_breakdown,
                    "peer_summary": sa.peer_summary,
                    "peer_count": sa.peer_count,
                    "peer_set_weak": sa.peer_set_weak,
                    "last_run_at": sa.peer_last_run_at.isoformat() if sa.peer_last_run_at else None,
                },
                "news_section": {
                    "verdict": sa.news_verdict,
                    "stock_signals": sa.news_stock_signals,
                    "source_count": sa.news_source_count,
                    "qualitative": sa.news_qualitative,
                    "last_run_at": sa.news_last_run_at.isoformat() if sa.news_last_run_at else None,
                },
                "act_now_score": sa.act_now_score,
                "summary_line": sa.summary_line,
            }
    except Exception as e:
        logger.warning(f"analyze: stock_card refresh failed for {symbol}: {e}")
        errors["stock_card"] = str(e)[:200]

    await db.commit()

    shareholding_data = None
    if shareholding:
        shareholding_data = {
            "quarter": shareholding.get("quarter"),
            "promoter_pct": shareholding.get("promoter_pct"),
            "promoter_pledge_pct": shareholding.get("promoter_pledge_pct"),
            "fii_pct": shareholding.get("fii_pct"),
            "dii_pct": shareholding.get("dii_pct"),
            "mf_pct": shareholding.get("mf_pct"),
            "insurance_pct": shareholding.get("insurance_pct"),
            "public_pct": shareholding.get("public_pct"),
        }

    return {
        "symbol": symbol,
        "exchange": exchange,
        "fundamentals": fund_data,
        "news_sentiment": sentiment,
        "mf_activity": {"available": bool(mf_act), **(mf_act or {})},
        "mf_buysell": {"available": bool(mf_bs), **(mf_bs or {})},
        "smart_money": sm,
        "shareholding": shareholding_data,
        "investment_decision": verdict,
        "stock_card": stock_card_data,
        "errors": errors if errors else None,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }
