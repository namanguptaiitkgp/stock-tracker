import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from kiteconnect import KiteConnect
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.daily_news_report import DailyNewsReport
from app.models.news_sentiment import NewsSentimentCache
from app.models.note import StockNote
from app.models.stock import Stock
from app.models.stock_peers import StockPeer
from app.models.user import User
from app.services.fii_dii import fetch_fii_dii_data, format_fii_dii
from app.services.mf_activity import get_mf_activity, get_mf_buysell
from app.services.fundamentals_service import get_fundamentals, serialize as serialize_fund
from app.services.news_scraper import run_morning_news_scan
from app.services.news_sentiment import get_news_sentiment
from app.services.options_service import fetch_option_chain_pcr

logger = logging.getLogger(__name__)
router = APIRouter()


def _compute_net_change(ltp, prev_close) -> float | None:
    if ltp is None or prev_close is None or prev_close == 0:
        return None
    return round(float(ltp) - float(prev_close), 2)


def _compute_change_pct(ltp, prev_close) -> float | None:
    if ltp is None or prev_close is None or prev_close == 0:
        return None
    return round((float(ltp) - float(prev_close)) / float(prev_close) * 100, 2)


def _kite(user: User) -> KiteConnect:
    if not user.kite_api_key or not user.kite_access_token:
        raise HTTPException(status_code=400, detail="Kite not connected")
    k = KiteConnect(api_key=user.kite_api_key)
    k.set_access_token(user.kite_access_token)
    return k


@router.get("/quote/{symbol}")
async def get_stock_detail(
    symbol: str,
    exchange: str = Query("NSE"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Full detail view for a single stock: Kite quote + OHLC + fundamentals + notes."""
    symbol = symbol.upper().strip()
    instrument_key = f"{exchange}:{symbol}"
    kite = _kite(user)

    # Parallel: quote, fundamentals, user note, holding (no historical — moved to /technicals)
    async def fetch_quote():
        try:
            return await asyncio.to_thread(kite.quote, [instrument_key])
        except Exception as e:
            logger.warning(f"quote failed for {instrument_key}: {e}")
            return {}

    async def fetch_fundamentals():
        try:
            return await get_fundamentals(symbol, db, exchange=exchange, user_id=user.id)
        except Exception:
            return None

    async def fetch_note():
        res = await db.execute(
            select(StockNote).where(StockNote.user_id == user.id, StockNote.symbol == symbol)
        )
        return res.scalar_one_or_none()

    async def fetch_holding():
        from app.services.portfolio_cache import get_holdings as cached_holdings
        try:
            holdings = await cached_holdings(user)
            for h in holdings:
                if h.get("tradingsymbol", "").upper() != symbol:
                    continue
                qty = h.get("quantity", 0) + h.get("collateral_quantity", 0) + h.get("t1_quantity", 0)
                if qty <= 0:
                    continue
                avg = h.get("average_price", 0)
                ltp = h.get("last_price", 0)
                invested = avg * qty
                current = ltp * qty
                pnl = current - invested
                collateral = h.get("collateral_quantity", 0)
                result = {
                    "quantity": qty,
                    "average_price": round(avg, 2),
                    "last_price": round(ltp, 2),
                    "invested": round(invested, 2),
                    "current_value": round(current, 2),
                    "pnl": round(pnl, 2),
                    "pnl_pct": round((pnl / invested * 100) if invested else 0, 2),
                    "day_change_pct": round(h.get("day_change_percentage", 0), 2),
                }
                if collateral > 0:
                    result["collateral_quantity"] = collateral
                    result["collateral_type"] = h.get("collateral_type", "pledge")
                return result
        except Exception as e:
            logger.warning(f"holdings fetch failed: {e}")
        return None

    quote_data, fund, note, holding = await asyncio.gather(
        fetch_quote(), fetch_fundamentals(), fetch_note(), fetch_holding()
    )

    # Parse Kite quote
    q = quote_data.get(instrument_key, {})
    ohlc_today = q.get("ohlc", {})
    depth = q.get("depth", {})

    return {
        "symbol": symbol,
        "exchange": exchange,

        # Portfolio holding (null if not owned)
        "holding": holding,

        # Kite quote data
        "last_price": q.get("last_price"),
        "volume": q.get("volume"),
        "average_price": q.get("average_price"),
        "last_quantity": q.get("last_quantity"),
        "last_trade_time": str(q.get("last_trade_time")) if q.get("last_trade_time") else None,
        "net_change": _compute_net_change(q.get("last_price"), ohlc_today.get("close")),
        "change_pct": _compute_change_pct(q.get("last_price"), ohlc_today.get("close")),
        "open": ohlc_today.get("open"),
        "high": ohlc_today.get("high"),
        "low": ohlc_today.get("low"),
        "close": ohlc_today.get("close"),
        "buy_quantity": q.get("buy_quantity"),
        "sell_quantity": q.get("sell_quantity"),
        "oi": q.get("oi"),
        "oi_day_high": q.get("oi_day_high"),
        "oi_day_low": q.get("oi_day_low"),
        "lower_circuit": q.get("lower_circuit_limit"),
        "upper_circuit": q.get("upper_circuit_limit"),

        # Market depth (top 5 bids/asks)
        "depth_buy": depth.get("buy", [])[:5],
        "depth_sell": depth.get("sell", [])[:5],

        # Fundamentals
        "fundamentals": serialize_fund(fund) if fund else None,

        # User note
        "note": {
            "content": note.content if note else "",
            "updated_at": note.updated_at.isoformat() if note and note.updated_at else None,
        },
    }


RANGE_TO_INTERVAL: dict[str, tuple[str, int]] = {
    # range_key -> (kite_interval, days_back)
    "1D": ("5minute", 1),
    "1W": ("15minute", 7),
    "1M": ("day", 30),
    "3M": ("day", 90),
    "1Y": ("day", 365),
    "5Y": ("day", 1825),
}


RANGE_TO_YFINANCE_PERIOD: dict[str, str] = {
    "1D": "1d",
    "1W": "5d",
    "1M": "1mo",
    "3M": "3mo",
    "1Y": "1y",
    "5Y": "5y",
}


def _yfinance_try_one(yf, candidate: str, period: str, interval: str) -> dict | None:
    """One yfinance attempt. Returns the dict shape on success, None on miss."""
    try:
        ticker = yf.Ticker(candidate)
        hist = ticker.history(period=period, interval=interval, auto_adjust=False)
        if hist is None or hist.empty:
            return None
        candles = []
        for idx, row in hist.iterrows():
            ts = idx.isoformat() if hasattr(idx, "isoformat") else str(idx)
            candles.append({
                "time": ts,
                "open": float(row["Open"]) if not _is_na(row["Open"]) else None,
                "high": float(row["High"]) if not _is_na(row["High"]) else None,
                "low":  float(row["Low"])  if not _is_na(row["Low"])  else None,
                "close": float(row["Close"]) if not _is_na(row["Close"]) else None,
                "volume": int(row["Volume"]) if not _is_na(row["Volume"]) else None,
            })
        current_price = None
        prev_close = None
        try:
            fi = ticker.fast_info
            current_price = float(fi.last_price) if getattr(fi, "last_price", None) else None
            prev_close = float(fi.previous_close) if getattr(fi, "previous_close", None) else None
        except Exception:
            pass
        if current_price is None and candles:
            current_price = candles[-1].get("close")
        return {
            "candles": candles,
            "current_price": current_price,
            "prev_close": prev_close,
        }
    except Exception:
        return None


def _yfinance_chart_sync(symbol: str, exchange: str, range_key: str, alt_symbols: list[str] | None = None) -> dict | None:
    """Free-source fallback when Kite is rate-limited / token expired.
    Tries the user's input plus any canonical alternates resolved server-side
    (e.g. ABBOTTINDIA → ABBOTINDIA from the instrument master), and the BSE
    suffix when the NSE one misses. Returns None only if every variant
    actually has no data on Yahoo.
    Runs synchronously — caller wraps in asyncio.to_thread."""
    try:
        import yfinance as yf  # local import — only on the cold path

        period = RANGE_TO_YFINANCE_PERIOD.get(range_key, "1mo")
        # `interval` for yfinance: intraday for 1D/1W, daily otherwise.
        interval = "5m" if range_key == "1D" else "30m" if range_key == "1W" else "1d"

        # Build the candidate list, in priority order: caller-provided
        # canonical alternates first, then the user's input, then BSE suffix.
        bases: list[str] = []
        for cand in (alt_symbols or []) + [symbol]:
            cu = (cand or "").upper().strip()
            if cu and cu not in bases:
                bases.append(cu)
        suffixes = [".NS"] if exchange == "NSE" else [".BO"]
        # Always cross-try the other exchange — instrument-master mapping is
        # noisy and a Monopoly stock might be on BSE only.
        suffixes.append(".BO" if exchange == "NSE" else ".NS")

        for base in bases:
            for suf in suffixes:
                hit = _yfinance_try_one(yf, f"{base}{suf}", period, interval)
                if hit:
                    return {**hit, "source": "yfinance"}
        return None
    except Exception as e:
        logger.info(f"yfinance fallback failed for {symbol}: {e}")
        return None


def _resolve_alt_symbols_sync(symbol: str, db_url_unused: object | None = None) -> list[str]:
    """Best-effort canonicalization: pull the instrument-master row whose
    name closely matches the input symbol's letters. Used by the chart
    endpoint when the user's saved symbol doesn't match an exchange ticker
    exactly (e.g. ABBOTTINDIA on the watchlist vs. ABBOTINDIA on NSE).
    Synchronous — runs inside a fresh sync engine so it's safe inside
    asyncio.to_thread."""
    return []  # placeholder — async-resolved version handled in the route below.


def _google_finance_price_only_sync(symbol: str, exchange: str) -> dict | None:
    """Final fallback when neither Kite nor yfinance know the symbol —
    Google Finance's quote scraper handles fuzzy lookups across exchanges.
    Returns just current_price + prev_close with an empty candles list so
    the card at least shows a number when the chart series is missing."""
    try:
        import asyncio
        from app.services.google_finance import lookup
        # `lookup` is async; build a private loop so this stays sync-friendly.
        loop = asyncio.new_event_loop()
        try:
            data = loop.run_until_complete(lookup(symbol, default_exchange=exchange))
        finally:
            loop.close()
        if not data or data.get("error") or data.get("last_price") is None:
            return None
        return {
            "candles": [],
            "current_price": float(data["last_price"]),
            "prev_close": float(data.get("prev_close")) if data.get("prev_close") is not None else None,
            "source": "google_finance",
        }
    except Exception as e:
        logger.info(f"google_finance fallback failed for {symbol}: {e}")
        return None


def _is_na(v) -> bool:
    """numpy/pandas NaN check that doesn't import pandas at module top."""
    try:
        return v != v  # NaN is the only value that doesn't equal itself
    except Exception:
        return v is None


@router.get("/chart/{symbol}")
async def get_chart_data(
    symbol: str,
    range: str = Query("1D"),
    exchange: str = Query("NSE"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Historical OHLC candles for a stock at the requested time range.

    Tries Kite first (best price + intraday granularity), falls back to
    yfinance if Kite rate-limits / errors / the user isn't connected. The
    response always carries `current_price` and `prev_close` when at least
    one source succeeded, so callers can render a CMP without a separate
    quote round-trip.
    """
    symbol = symbol.upper().strip()
    range_key = range.upper()
    if range_key not in RANGE_TO_INTERVAL:
        raise HTTPException(status_code=400, detail=f"Invalid range. Use one of: {list(RANGE_TO_INTERVAL.keys())}")

    interval, days_back = RANGE_TO_INTERVAL[range_key]

    # ---- Path 1: Kite (when connected) ---------------------------------- #
    candles_out: list[dict] = []
    current_price: float | None = None
    prev_close: float | None = None
    source = "kite"
    kite_err: str | None = None

    if user.kite_api_key and user.kite_access_token:
        try:
            kite = _kite(user)

            res = await db.execute(
                select(Stock).where(Stock.tradingsymbol == symbol, Stock.exchange == exchange)
            )
            stock = res.scalar_one_or_none()
            if not stock or not stock.instrument_token:
                kite_err = "instrument_token_missing"
            else:
                end = datetime.now(timezone.utc)
                start = end - timedelta(days=days_back)
                candles = await asyncio.to_thread(
                    kite.historical_data,
                    stock.instrument_token,
                    start.date() if interval == "day" else start,
                    end.date() if interval == "day" else end,
                    interval,
                )
                for c in candles:
                    ts = c.get("date")
                    candles_out.append({
                        "time": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                        "open": c.get("open"),
                        "high": c.get("high"),
                        "low": c.get("low"),
                        "close": c.get("close"),
                        "volume": c.get("volume"),
                    })

                # Quote for prev_close + current_price.
                try:
                    instrument_key = f"{exchange}:{symbol}"
                    quote_data = await asyncio.to_thread(kite.quote, [instrument_key])
                    q = quote_data.get(instrument_key, {})
                    prev_close = q.get("ohlc", {}).get("close")
                    current_price = q.get("last_price")
                except Exception:
                    pass
                if current_price is None and candles_out:
                    current_price = candles_out[-1].get("close")
        except Exception as e:
            kite_err = str(e)
            logger.warning(f"chart kite failed for {symbol} ({interval}, {days_back}d): {e}")
            candles_out = []  # ensure fallback fires below

    # ---- Path 2: yfinance fallback -------------------------------------- #
    if not candles_out:
        # Pull canonical NSE tickers from the instrument master via a
        # letters-only fuzzy match. Handles cases like
        # `ABBOTTINDIA` (watchlist input) → `ABBOTINDIA` (canonical) — same
        # consonants in order, different lengths.
        alt_syms: list[str] = []
        try:
            letters = "".join(c for c in symbol.upper() if c.isalpha())
            if letters:
                # Compact form (drop repeated chars) and a name LIKE search
                # both contribute candidates.
                compact = ""
                for ch in letters:
                    if not compact or compact[-1] != ch:
                        compact += ch
                if compact != letters:
                    alt_syms.append(compact)
                # Name-based lookup against the Stock table.
                rows = await db.execute(
                    select(Stock.tradingsymbol)
                    .where(Stock.exchange == exchange)
                    .where(Stock.name.ilike(f"%{letters[:6]}%"))
                    .limit(5)
                )
                for (ts,) in rows.all():
                    if ts and ts not in alt_syms:
                        alt_syms.append(ts)
        except Exception:
            pass

        fb = await asyncio.to_thread(
            _yfinance_chart_sync, symbol, exchange, range_key, alt_syms,
        )
        if fb is None:
            # Last-ditch: Google Finance scraper does its own fuzzy match
            # and at least returns a current price even when no chart series
            # is available. Empty candles → frontend renders a price-only
            # card.
            fb = await asyncio.to_thread(_google_finance_price_only_sync, symbol, exchange)
        if fb is None:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"Failed to fetch chart data ({kite_err or 'no_kite'}); "
                    "yfinance + Google Finance fallbacks empty."
                ),
            )
        candles_out = fb["candles"]
        current_price = fb.get("current_price")
        prev_close = fb.get("prev_close")
        source = fb.get("source", "yfinance")

    return {
        "symbol": symbol,
        "exchange": exchange,
        "range": range_key,
        "interval": interval,
        "candles": candles_out,
        "current_price": current_price,
        "prev_close": prev_close,
        "source": source,
    }


@router.get("/technicals/{symbol}")
async def get_technicals(
    symbol: str,
    exchange: str = Query("NSE"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Historical-derived indicators: DMAs, 52-week range, period returns, tech signal.

    Split out from /quote because the 365-day Kite historical fetch is the slowest
    call in the panel; the rest of the panel can render while this loads.
    """
    symbol = symbol.upper().strip()
    instrument_key = f"{exchange}:{symbol}"
    kite = _kite(user)

    # Resolve instrument token
    res = await db.execute(
        select(Stock).where(Stock.tradingsymbol == symbol, Stock.exchange == exchange)
    )
    stock = res.scalar_one_or_none()
    token = stock.instrument_token if stock else None

    # Fetch historical and current LTP in parallel
    async def fetch_ohlc():
        if not token:
            return []
        try:
            return await asyncio.to_thread(
                kite.historical_data,
                token,
                date.today() - timedelta(days=365),
                date.today(),
                "day",
            )
        except Exception as e:
            logger.warning(f"technicals historical_data failed for {symbol}: {e}")
            return []

    async def fetch_ltp():
        try:
            qd = await asyncio.to_thread(kite.quote, [instrument_key])
            return qd.get(instrument_key, {}).get("last_price")
        except Exception:
            return None

    ohlc, ltp = await asyncio.gather(fetch_ohlc(), fetch_ltp())

    # Build (close, date) pairs over the 52w window for high/low + dates
    window_252 = [c for c in ohlc if c.get("close")][-252:] if len([c for c in ohlc if c.get("close")]) >= 60 else [c for c in ohlc if c.get("close")]
    closes = [c["close"] for c in window_252]
    high_52w = max(closes) if closes else None
    low_52w = min(closes) if closes else None

    def _date_for(target_value):
        if target_value is None:
            return None
        # Find the latest occurrence of the max/min close
        for c in reversed(window_252):
            if c["close"] == target_value:
                d = c.get("date")
                return d.isoformat() if hasattr(d, "isoformat") else str(d) if d else None
        return None

    high_52w_date = _date_for(high_52w)
    low_52w_date = _date_for(low_52w)

    # DMAs computed over the FULL closes list (longer than the 52w window doesn't matter for SMA over recent N)
    closes_all = [c["close"] for c in ohlc if c.get("close")]
    dma20 = sum(closes_all[-20:]) / len(closes_all[-20:]) if len(closes_all) >= 20 else None
    dma50 = sum(closes_all[-50:]) / len(closes_all[-50:]) if len(closes_all) >= 50 else None
    dma200 = sum(closes_all[-200:]) / len(closes_all[-200:]) if len(closes_all) >= 200 else None
    closes = closes_all  # keep below code working for _ret/tech_signal that reference `closes`

    def _ret(days):
        if len(closes) <= days:
            return None
        return round((closes[-1] - closes[-(days + 1)]) / closes[-(days + 1)] * 100, 2)

    tech_signal = None
    if ltp and (dma20 or dma50 or dma200):
        above, below = [], []
        for ma_val, ma_label in [(dma20, "20D"), (dma50, "50D"), (dma200, "200D")]:
            if ma_val is None:
                continue
            if ltp > ma_val:
                above.append(ma_label)
            else:
                below.append(ma_label)
        total = len(above) + len(below)
        if total > 0:
            score = (len(above) - len(below)) / total
            if score >= 0.5:
                direction = "accumulating"
                label = "Above " + " & ".join(above) + " MA"
            elif score <= -0.5:
                direction = "distributing"
                label = "Below " + " & ".join(below) + " MA"
            else:
                direction = "neutral"
                label = f"Above {above[0]}, below {below[0]}" if above and below else "Mixed signals"
            tech_signal = {
                "direction": direction,
                "label": label,
                "strength": int(abs(score) * 100),
            }

    pct_from_52w_high = None
    pct_from_52w_low = None
    if ltp and high_52w and high_52w > 0:
        pct_from_52w_high = round((ltp - high_52w) / high_52w * 100, 2)
    if ltp and low_52w and low_52w > 0:
        pct_from_52w_low = round((ltp - low_52w) / low_52w * 100, 2)

    return {
        "symbol": symbol,
        "exchange": exchange,
        "dma20": round(dma20, 2) if dma20 else None,
        "dma50": round(dma50, 2) if dma50 else None,
        "dma200": round(dma200, 2) if dma200 else None,
        "high_52w": round(high_52w, 2) if high_52w else None,
        "low_52w": round(low_52w, 2) if low_52w else None,
        "high_52w_date": high_52w_date,
        "low_52w_date": low_52w_date,
        "pct_from_52w_high": pct_from_52w_high,
        "pct_from_52w_low": pct_from_52w_low,
        "return_1m": _ret(22),
        "return_3m": _ret(66),
        "return_6m": _ret(132),
        "return_1y": _ret(252),
        "tech_signal": tech_signal,
    }


@router.get("/options/{symbol}/pcr")
async def get_options_pcr(
    symbol: str,
    _user: User = Depends(get_current_user),
) -> dict:
    """Put/Call ratio + max pain for an F&O stock from NSE option chain."""
    data = await fetch_option_chain_pcr(symbol)
    if not data:
        return {"symbol": symbol.upper().strip(), "pcr": None, "available": False}
    return {**data, "available": True}


SENTIMENT_CACHE_HOURS = 12


@router.get("/sentiment/{symbol}")
async def get_sentiment(
    symbol: str,
    days: int = Query(7, ge=1, le=90),
    force: bool = Query(False),
    cache_only: bool = Query(False),
    custom_query: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    symbol = symbol.upper().strip()

    # Check cache (skip if force refresh or custom query)
    if not force and not custom_query:
        result = await db.execute(
            select(NewsSentimentCache).where(NewsSentimentCache.symbol == symbol)
            .order_by(NewsSentimentCache.analyzed_at.desc()).limit(1)
        )
        cached = result.scalar_one_or_none()

        if cached and cached.analyzed_at:
            age = datetime.now(timezone.utc) - cached.analyzed_at
            if cache_only or age < timedelta(hours=SENTIMENT_CACHE_HOURS):
                return cached.result_json

        if cache_only:
            return {"symbol": symbol, "sentiment": None, "cached": False}

    # Fetch fresh
    from app.models.fundamentals import StockFundamentals
    fund_result = await db.execute(
        select(StockFundamentals).where(StockFundamentals.symbol == symbol)
    )
    fund = fund_result.scalar_one_or_none()
    company_name = fund.name if fund else None

    if custom_query:
        # Use custom search query instead of auto-generated
        from app.services.news_sentiment import fetch_google_news_custom, analyze_sentiment
        headlines = await fetch_google_news_custom(custom_query, days=days)
        sentiment = await analyze_sentiment(symbol, company_name or symbol, headlines, user.id, db)
        sentiment["symbol"] = symbol
        sentiment["analyzed_at"] = datetime.now(timezone.utc).isoformat()
        sentiment["headline_count"] = len(headlines)
        sentiment["days_analyzed"] = days
        sentiment["custom_query"] = custom_query
    else:
        sentiment = await get_news_sentiment(symbol, company_name, days=days, user_id=user.id, db=db)

    # Save to cache
    record = NewsSentimentCache(
        symbol=symbol,
        sentiment=sentiment.get("sentiment"),
        score=sentiment.get("score"),
        result_json=sentiment,
        analyzed_at=datetime.now(timezone.utc),
    )
    db.add(record)
    await db.commit()

    return sentiment


@router.post("/sentiment/{symbol}/refresh")
async def refresh_sentiment(
    symbol: str,
    days: int = Query(7, ge=1, le=30),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    symbol = symbol.upper().strip()

    from app.models.fundamentals import StockFundamentals
    fund_result = await db.execute(
        select(StockFundamentals).where(StockFundamentals.symbol == symbol)
    )
    fund = fund_result.scalar_one_or_none()
    company_name = fund.name if fund else None

    sentiment = await get_news_sentiment(symbol, company_name, days=days, user_id=user.id, db=db)

    record = NewsSentimentCache(
        symbol=symbol,
        sentiment=sentiment.get("sentiment"),
        score=sentiment.get("score"),
        result_json=sentiment,
        analyzed_at=datetime.now(timezone.utc),
    )
    db.add(record)
    await db.commit()

    return sentiment


@router.get("/fii-dii")
async def get_fii_dii(
    _user: User = Depends(get_current_user),
) -> dict:
    """Get today's FII/DII trading activity from NSE."""
    raw = await fetch_fii_dii_data()
    return format_fii_dii(raw)


@router.get("/news-reports/latest")
async def get_latest_news_report(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(DailyNewsReport)
        .where(DailyNewsReport.user_id == user.id)
        .order_by(DailyNewsReport.created_at.desc())
        .limit(1)
    )
    record = result.scalar_one_or_none()
    if not record:
        return {"status": "no_reports", "message": "No news reports yet. Click 'Run Scan' to generate one."}

    data = dict(record.result_json)
    data["id"] = record.id
    data["created_at"] = record.created_at.isoformat() if record.created_at else None
    return data


@router.get("/news-reports/history")
async def list_news_reports(
    limit: int = Query(30, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    result = await db.execute(
        select(DailyNewsReport)
        .where(DailyNewsReport.user_id == user.id)
        .order_by(DailyNewsReport.created_at.desc())
        .limit(limit)
    )
    reports = result.scalars().all()
    return [
        {
            "id": r.id,
            "report_date": r.report_date.isoformat() if r.report_date else None,
            "total_headlines": r.total_headlines,
            "companies_found": r.companies_found,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in reports
    ]


@router.get("/news-reports/{report_id}")
async def get_news_report(
    report_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(DailyNewsReport).where(
            DailyNewsReport.id == report_id,
            DailyNewsReport.user_id == user.id,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Report not found")
    data = dict(record.result_json)
    data["id"] = record.id
    data["created_at"] = record.created_at.isoformat() if record.created_at else None
    return data


@router.post("/news-reports/run-now")
async def run_news_scan_now(
    holdings_only: bool = Query(False),
    fno_only: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from datetime import date as date_type
    from app.services.portfolio_cache import get_holdings as cached_holdings

    # If holdings_only, get the user's portfolio symbols to filter results
    portfolio_symbols: set[str] | None = None
    if holdings_only and user.kite_api_key and user.kite_access_token:
        try:
            holdings = await cached_holdings(user)
            from app.services.portfolio_cache import holding_total_qty
            portfolio_symbols = {
                h.get("tradingsymbol", "").upper()
                for h in holdings
                if holding_total_qty(h) > 0
            }
        except Exception:
            logger.exception("holdings fetch failed for morning-news-scan filter")

    fno_symbols: set[str] | None = None
    if fno_only:
        from app.services.market.fno_universe import get_fno_sets
        nse, _ = await get_fno_sets()
        fno_symbols = nse

    report = await run_morning_news_scan(user_id=user.id, db=db)

    # Filter by requested scope
    if report.get("companies"):
        all_companies = report["companies"]
        filters_applied: list[str] = []
        if portfolio_symbols is not None:
            all_companies = [c for c in all_companies if c.get("symbol", "").upper() in portfolio_symbols]
            filters_applied.append("holdings_only")
        if fno_symbols is not None:
            all_companies = [c for c in all_companies if c.get("symbol", "").upper() in fno_symbols]
            filters_applied.append("fno_only")
        if filters_applied:
            report["companies"] = all_companies
            report["companies_found"] = len(all_companies)
            report["filter"] = "+".join(filters_applied)
            if portfolio_symbols is not None:
                report["portfolio_size"] = len(portfolio_symbols)
            if fno_symbols is not None:
                report["fno_universe_size"] = len(fno_symbols)

    # Mirror each company's sentiment into news_sentiment_cache so that
    # per-symbol views (F&O table, Today holdings rows, watchlist) pick
    # up fresh sentiment without having to open each stock individually.
    from datetime import datetime as _dt, timezone as _tz
    _now_utc = _dt.now(tz=_tz.utc)
    for c in (report.get("companies") or []):
        sym = (c.get("symbol") or "").upper()
        if not sym:
            continue
        payload = {
            "summary": c.get("summary"),
            "headlines": c.get("headlines") or [],
            "name": c.get("name"),
            "headline_count": c.get("headline_count") or 0,
            "source_report_date": report.get("report_date"),
        }
        existing = await db.execute(
            select(NewsSentimentCache).where(NewsSentimentCache.symbol == sym)
        )
        prev = existing.scalar_one_or_none()
        if prev:
            prev.sentiment = c.get("sentiment") or "neutral"
            prev.score = c.get("score") or 0
            prev.result_json = payload
            prev.analyzed_at = _now_utc
        else:
            db.add(NewsSentimentCache(
                symbol=sym,
                sentiment=c.get("sentiment") or "neutral",
                score=c.get("score") or 0,
                result_json=payload,
                analyzed_at=_now_utc,
            ))

    record = DailyNewsReport(
        user_id=user.id,
        report_date=date_type.today(),
        total_headlines=report.get("total_headlines", 0),
        companies_found=report.get("companies_found", 0),
        result_json=report,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    report["id"] = record.id
    report["created_at"] = record.created_at.isoformat() if record.created_at else None
    return report


@router.get("/mf-activity/{symbol}")
async def get_mutual_fund_activity(
    symbol: str,
    _user: User = Depends(get_current_user),
) -> dict:
    symbol = symbol.upper().strip()
    result = await get_mf_activity(symbol)
    if not result:
        return {"symbol": symbol, "available": False}
    return {"symbol": symbol, "available": True, **result}


@router.get("/mf-buysell/{symbol}")
async def get_mf_buysell_activity(
    symbol: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get MF buy/sell changes for a stock from mfdata.in."""
    symbol = symbol.upper().strip()

    # Get company name from fundamentals for mfdata.in lookup
    from app.models.fundamentals import StockFundamentals
    fund_result = await db.execute(
        select(StockFundamentals).where(StockFundamentals.symbol == symbol)
    )
    fund = fund_result.scalar_one_or_none()
    company_name = fund.name if fund else None

    result = await get_mf_buysell(symbol, company_name)
    if not result:
        return {"symbol": symbol, "available": False}
    return {"symbol": symbol, "available": True, **result}


@router.post("/peers/{symbol}/generate")
async def generate_peer_stocks(
    symbol: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Call Gemini to discover true peers and store them bidirectionally."""
    from app.services.peer_discovery import generate_peers
    return await generate_peers(symbol.upper().strip(), db, user)


@router.post("/peers/backfill")
async def trigger_peer_backfill(
    user: User = Depends(get_current_user),
) -> dict:
    """Kick off a one-shot Celery job that generates peers for every holding
    and watchlist symbol that doesn't have any. Returns the Celery task id."""
    from app.tasks.peer_backfill_task import run_peer_backfill
    result = run_peer_backfill.delay(user.id)
    return {"task_id": result.id, "status": "queued"}


@router.get("/peers/{symbol}")
async def get_peer_stocks(
    symbol: str,
    limit: int = 8,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return peers: stored (Gemini-generated) first, sector-based fallback.

    Each peer row now includes a `composite_score` (0-100) computed from
    PE/PB/ROE/RevGrowth/Margin relative to the cohort median. Higher score
    means cheaper + higher quality vs peers."""
    from statistics import median
    from app.models.fundamentals import StockFundamentals
    from app.services.peer_discovery import get_effective_peers, get_stored_peers  # noqa: F401

    symbol = symbol.upper().strip()

    result = await db.execute(
        select(StockFundamentals).where(StockFundamentals.symbol == symbol)
    )
    stock = result.scalar_one_or_none()
    if not stock or not stock.sector:
        return {"symbol": symbol, "sector": None, "industry": None, "peers": [], "source": "none"}

    # Lazy trigger: when stored peers < 2, fire warmup async so the next
    # view sees Gemini-discovered peers. Returns current (fallback) peers
    # right now without waiting. Caught by stock_peers row existence to
    # avoid hammering Celery on every dashboard poll.
    try:
        stored_count_q = await db.execute(
            select(func.count()).select_from(StockPeer).where(StockPeer.symbol == symbol)
        )
        stored_count = stored_count_q.scalar_one() or 0
        if stored_count < 2:
            from app.tasks.peer_warmup_task import warm_peers_for_symbol
            # chain_analysis=False — don't block on the 30s refresh_stock_analysis
            # for an interactive request. The chain runs from morning_pipeline.
            warm_peers_for_symbol.delay(symbol, user.id, chain_analysis=False)
    except Exception as e:  # pragma: no cover — best-effort
        logger.warning("peers endpoint: lazy warmup dispatch failed for %s: %s", symbol, e)

    def peer_row(p: StockFundamentals, rationale: str | None = None) -> dict:
        cmp = float(p.cmp) if p.cmp else None
        high = float(p.high_52w) if p.high_52w else None
        low = float(p.low_52w) if p.low_52w else None
        pct_high = ((cmp - high) / high * 100) if (cmp and high) else None
        pct_low = ((cmp - low) / low * 100) if (cmp and low) else None
        row = {
            "symbol": p.symbol,
            "name": p.name,
            "cmp": cmp,
            "market_cap": float(p.market_cap) if p.market_cap else None,
            "pe_ratio": float(p.pe_ratio) if p.pe_ratio else None,
            "pb_ratio": float(p.pb_ratio) if p.pb_ratio else None,
            "roe": float(p.roe) if p.roe else None,
            "revenue_growth_1y": float(p.revenue_growth_1y) if p.revenue_growth_1y else None,
            "net_profit_margin": float(p.net_profit_margin) if p.net_profit_margin else None,
            "promoter_holding": float(p.promoter_holding) if p.promoter_holding else None,
            "high_52w": high,
            "low_52w": low,
            "pct_from_52w_high": round(pct_high, 2) if pct_high is not None else None,
            "pct_from_52w_low": round(pct_low, 2) if pct_low is not None else None,
        }
        if rationale:
            row["rationale"] = rationale
        return row

    # Composite score: averages metric-by-metric score vs the cohort median.
    # Each metric contributes its weight; inverted multiples (PE/PB) score
    # higher when the stock is *cheaper*. Score is 0-100 (50 = at-median).
    _SCORE_METRICS = {
        "pe_ratio":          (0.25, True),   # inverted (lower = better)
        "pb_ratio":          (0.20, True),   # inverted
        "roe":               (0.25, False),
        "net_profit_margin": (0.15, False),
        "revenue_growth_1y": (0.15, False),
    }

    def _compute_composites(rows: list[dict]) -> None:
        """Mutates rows in-place, adding `composite_score`. Subject row
        (is_self) is scored against peers; peer rows are scored against
        the same cohort median (peers excluding self)."""
        peer_only = [r for r in rows if not r.get("is_self")]
        if not peer_only:
            return
        medians: dict[str, float] = {}
        for m in _SCORE_METRICS:
            vals = [r.get(m) for r in peer_only if r.get(m) is not None]
            if vals:
                medians[m] = median(vals)
        for r in rows:
            total_w = 0.0
            score_acc = 0.0
            for m, (w, inverted) in _SCORE_METRICS.items():
                med = medians.get(m)
                v = r.get(m)
                if med is None or v is None or med == 0:
                    continue
                ratio = v / med
                # Clamp to a reasonable band so a 10× outlier doesn't dominate.
                ratio = max(0.25, min(ratio, 4.0))
                if inverted:
                    # ratio < 1 means cheaper than peers → higher score.
                    # Map ratio in [0.25, 4.0] linearly to [100, 0].
                    sub = (4.0 - ratio) / (4.0 - 0.25) * 100.0
                else:
                    # ratio > 1 means better than peers → higher score.
                    sub = (ratio - 0.25) / (4.0 - 0.25) * 100.0
                score_acc += sub * w
                total_w += w
            r["composite_score"] = round(score_acc / total_w, 1) if total_w > 0 else None

    self_row = peer_row(stock)
    self_row["is_self"] = True

    # Use the shared resolver so the detail panel's peer cards and the
    # dashboard verdict (from evaluate_peers) always show the same companies.
    # Always supplements toward `target` even when some stored peers exist —
    # niche stocks (Capital Markets, niche Travel/Retail) no longer stop at
    # 2 peers when 4-6 sector peers are available in fundamentals.
    effective, source = await get_effective_peers(symbol, db, target=limit)
    sym_list = [p["symbol"] for p in effective][:limit]
    rationale_map = {p["symbol"]: p.get("rationale") for p in effective}

    if sym_list:
        fund_q = await db.execute(
            select(StockFundamentals).where(StockFundamentals.symbol.in_(sym_list))
        )
        fund_map = {f.symbol: f for f in fund_q.scalars().all()}
        rows = [self_row]
        for sym in sym_list:
            f = fund_map.get(sym)
            if f:
                rows.append(peer_row(f, rationale_map.get(sym)))
        _compute_composites(rows)
        return {
            "symbol": symbol, "sector": stock.sector, "industry": stock.industry,
            "peers": rows, "source": source,
        }

    return {
        "symbol": symbol, "sector": stock.sector, "industry": stock.industry,
        "peers": [self_row], "source": "none",
    }
