"""Smart-money API: composite signal, leaderboard, shark radar, runs log.

Rendered into the frontend's /smart-money page and the per-stock SmartMoneyPanel.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import hashlib
from dataclasses import asdict

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import case, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.smart_money import (
    AnalyzerSession,
    AnalyzerSessionFile,
    BhavcopyDaily,
    BulkBlockDeal,
    IngestionRun,
    KnownShark,
    SmartMoneySignal,
)
from app.models.user import User
from app.services.smart_money.run_logger import SOURCE_CADENCE_HOURS

router = APIRouter()


def _f(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


def _serialize_deal(d: BulkBlockDeal) -> dict:
    return {
        "trade_date": d.trade_date.isoformat(),
        "exchange": d.exchange,
        "symbol": d.symbol,
        "security_name": d.security_name_raw,
        "client_name": d.client_name_raw,
        "side": d.side,
        "quantity": int(d.quantity) if d.quantity is not None else 0,
        "avg_price": _f(d.avg_price),
        "trade_value_inr": _f(d.trade_value_inr),
        "deal_type": d.deal_type,
        "is_known_shark": d.is_known_shark,
    }


def _serialize_signal(sig: SmartMoneySignal) -> dict:
    return {
        "symbol": sig.symbol,
        "as_of": sig.as_of.isoformat(),
        "mf_score": _f(sig.mf_score),
        "pms_score": _f(sig.pms_score),
        "aif_score": _f(sig.aif_score),
        "deals_score": _f(sig.deals_score),
        "delivery_score": _f(sig.delivery_score),
        "composite": _f(sig.composite),
        # Three-stream system (PR 2 onwards). Frontend reads these in PR 5.
        "conviction_score": _f(sig.conviction_score),
        "flow_score": _f(sig.flow_score),
        "red_flag_score": _f(sig.red_flag_score),
        "signal_breakdown": sig.signal_breakdown,
        "top_adders": sig.top_adders,
        "top_reducers": sig.top_reducers,
        "named_sharks": sig.named_sharks,
        "meta": sig.meta,
    }


@router.get("/runs/latest")
async def runs_latest(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """One summary row per source, with stale flag based on cadence×1.5."""
    sources = list(SOURCE_CADENCE_HOURS.keys())
    out = []
    now = datetime.now(tz=timezone.utc)

    for source in sources:
        last_success = await db.execute(
            select(IngestionRun)
            .where(IngestionRun.source == source, IngestionRun.status == "success")
            .order_by(desc(IngestionRun.finished_at))
            .limit(1)
        )
        ls = last_success.scalar_one_or_none()

        last_any = await db.execute(
            select(IngestionRun)
            .where(IngestionRun.source == source)
            .order_by(desc(IngestionRun.started_at))
            .limit(1)
        )
        la = last_any.scalar_one_or_none()

        cadence_hours = SOURCE_CADENCE_HOURS.get(source, 30)
        stale = True
        if ls and ls.finished_at:
            delta_h = (now - ls.finished_at).total_seconds() / 3600.0
            stale = delta_h > cadence_hours * 1.5

        out.append({
            "source": source,
            "last_success_at": ls.finished_at.isoformat() if ls and ls.finished_at else None,
            "last_run_at": la.started_at.isoformat() if la and la.started_at else None,
            "last_run_status": la.status if la else None,
            "last_run_error": la.error_message if la and la.status == "failed" else None,
            "cadence_hours": cadence_hours,
            "stale": stale,
            "records_inserted": ls.records_inserted if ls else 0,
        })

    return {"sources": out, "generated_at": now.isoformat()}


@router.get("/runs")
async def runs_list(
    source: str | None = None,
    status: str | None = None,
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    q = select(IngestionRun).order_by(desc(IngestionRun.started_at)).limit(limit)
    if source:
        q = q.where(IngestionRun.source == source)
    if status:
        q = q.where(IngestionRun.status == status)

    result = await db.execute(q)
    rows = result.scalars().all()
    return {
        "runs": [
            {
                "id": r.id,
                "source": r.source,
                "task_name": r.task_name,
                "status": r.status,
                "triggered_by": r.triggered_by,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "duration_ms": r.duration_ms,
                "records_fetched": r.records_fetched,
                "records_inserted": r.records_inserted,
                "records_updated": r.records_updated,
                "records_skipped": r.records_skipped,
                "warnings": r.warnings,
                "error_class": r.error_class,
                "error_message": r.error_message,
                "meta": r.meta,
            }
            for r in rows
        ]
    }


@router.get("/pulse")
async def pulse(
    days: int = Query(default=7, le=60),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Market-wide net flows over a rolling window."""
    since = datetime.now().date() - timedelta(days=days)

    # Bulk/block total value + buy/sell split
    deal_stats = await db.execute(
        select(
            BulkBlockDeal.side,
            func.count(BulkBlockDeal.id),
            func.sum(BulkBlockDeal.trade_value_inr),
        )
        .where(BulkBlockDeal.trade_date >= since)
        .group_by(BulkBlockDeal.side)
    )
    buy_count, buy_value = 0, 0.0
    sell_count, sell_value = 0, 0.0
    for side, cnt, val in deal_stats.all():
        v = _f(val) or 0.0
        if side == "BUY":
            buy_count, buy_value = cnt, v
        elif side == "SELL":
            sell_count, sell_value = cnt, v

    # Named sharks count
    shark_cnt = await db.execute(
        select(func.count(BulkBlockDeal.id))
        .where(BulkBlockDeal.trade_date >= since, BulkBlockDeal.is_known_shark.is_(True))
    )
    shark_total = shark_cnt.scalar_one() or 0

    # Top 10 stocks by composite (latest signal per symbol)
    latest_as_of = await db.execute(select(func.max(SmartMoneySignal.as_of)))
    latest_day = latest_as_of.scalar_one_or_none()
    top_positive = []
    top_negative = []
    if latest_day:
        pos = await db.execute(
            select(SmartMoneySignal)
            .where(SmartMoneySignal.as_of == latest_day, SmartMoneySignal.composite.is_not(None))
            .order_by(desc(SmartMoneySignal.composite))
            .limit(10)
        )
        top_positive = [_serialize_signal(s) for s in pos.scalars().all()]
        neg = await db.execute(
            select(SmartMoneySignal)
            .where(SmartMoneySignal.as_of == latest_day, SmartMoneySignal.composite.is_not(None))
            .order_by(SmartMoneySignal.composite.asc())
            .limit(10)
        )
        top_negative = [_serialize_signal(s) for s in neg.scalars().all()]

    return {
        "window_days": days,
        "since": since.isoformat(),
        "deals": {
            "buy_count": buy_count,
            "sell_count": sell_count,
            "buy_value_inr": buy_value,
            "sell_value_inr": sell_value,
            "net_value_inr": buy_value - sell_value,
            "shark_count": shark_total,
        },
        "latest_signal_date": latest_day.isoformat() if latest_day else None,
        "top_positive": top_positive,
        "top_negative": top_negative,
    }


@router.get("/leaderboard")
async def leaderboard(
    metric: str = Query(
        default="composite",
        pattern="^(composite|deals|delivery|shark_trades|conviction|flow|red_flags)$",
    ),
    limit: int = Query(default=20, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Top-N stocks by a chosen smart-money metric."""
    if metric == "shark_trades":
        since = datetime.now().date() - timedelta(days=30)
        result = await db.execute(
            select(
                BulkBlockDeal.symbol,
                func.count(BulkBlockDeal.id).label("n"),
                func.sum(BulkBlockDeal.trade_value_inr).label("val"),
            )
            .where(
                BulkBlockDeal.trade_date >= since,
                BulkBlockDeal.is_known_shark.is_(True),
            )
            .group_by(BulkBlockDeal.symbol)
            .order_by(desc("val"))
            .limit(limit)
        )
        return {
            "metric": metric,
            "rows": [
                {"symbol": sym, "trade_count": n, "total_value_inr": _f(val)}
                for sym, n, val in result.all()
            ],
        }

    latest_day_q = await db.execute(select(func.max(SmartMoneySignal.as_of)))
    latest_day = latest_day_q.scalar_one_or_none()
    if not latest_day:
        return {"metric": metric, "rows": []}

    col_map = {
        "composite": SmartMoneySignal.composite,
        "deals": SmartMoneySignal.deals_score,
        "delivery": SmartMoneySignal.delivery_score,
        "conviction": SmartMoneySignal.conviction_score,
        "flow": SmartMoneySignal.flow_score,
        "red_flags": SmartMoneySignal.red_flag_score,
    }
    col = col_map[metric]
    # Red flags sort ascending (most negative = worst); everything else descending.
    order_clause = col.asc() if metric == "red_flags" else desc(col)
    result = await db.execute(
        select(SmartMoneySignal)
        .where(SmartMoneySignal.as_of == latest_day, col.is_not(None))
        .order_by(order_clause)
        .limit(limit)
    )
    return {
        "metric": metric,
        "as_of": latest_day.isoformat(),
        "rows": [_serialize_signal(s) for s in result.scalars().all()],
    }


@router.get("/shark/{name}")
async def shark_detail(
    name: str,
    days: int = Query(default=180, le=1825),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Trade timeline for a specific named shark (matched by client_name_norm
    against known_sharks aliases)."""
    from app.services.smart_money.deals import _norm_client

    since = datetime.now().date() - timedelta(days=days)

    shark = await db.execute(
        select(KnownShark).where(KnownShark.canonical_name.ilike(name))
    )
    shark_row = shark.scalar_one_or_none()

    # Build normalized-name list to match
    norms: list[str] = []
    display = name
    if shark_row:
        display = shark_row.display_name
        norms.append(_norm_client(shark_row.canonical_name))
        for alias in (shark_row.aliases or []):
            norms.append(_norm_client(alias))
    else:
        norms.append(_norm_client(name))

    deals_q = await db.execute(
        select(BulkBlockDeal)
        .where(
            BulkBlockDeal.client_name_norm.in_(norms),
            BulkBlockDeal.trade_date >= since,
        )
        .order_by(desc(BulkBlockDeal.trade_date))
    )
    deals = [_serialize_deal(d) for d in deals_q.scalars().all()]

    return {
        "shark": {
            "canonical_name": shark_row.canonical_name if shark_row else name,
            "display_name": display,
            "aliases": (shark_row.aliases or []) if shark_row else [],
        },
        "window_days": days,
        "deal_count": len(deals),
        "deals": deals,
    }


@router.get("/top-clients")
async def top_clients(
    days: int = Query(default=30, le=365),
    limit: int = Query(default=30, le=100),
    side: str | None = Query(default=None, pattern="^(BUY|SELL)$"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Most active bulk/block-deal participants over a window — includes
    everyone (not just curated sharks). Click-through goes to /shark/{name}
    which will match by normalized name even if not in known_sharks."""
    since = datetime.now().date() - timedelta(days=days)

    q = (
        select(
            BulkBlockDeal.client_name_norm,
            func.min(BulkBlockDeal.client_name_raw).label("display"),
            func.count(BulkBlockDeal.id).label("trades"),
            func.sum(BulkBlockDeal.trade_value_inr).label("total_value"),
            func.sum(
                case((BulkBlockDeal.side == "BUY", BulkBlockDeal.trade_value_inr), else_=0)
            ).label("buy_value"),
            func.sum(
                case((BulkBlockDeal.side == "SELL", BulkBlockDeal.trade_value_inr), else_=0)
            ).label("sell_value"),
            func.bool_or(BulkBlockDeal.is_known_shark).label("is_shark"),
            func.count(func.distinct(BulkBlockDeal.symbol)).label("stock_count"),
        )
        .where(BulkBlockDeal.trade_date >= since)
        .group_by(BulkBlockDeal.client_name_norm)
        .order_by(desc("total_value"))
        .limit(limit)
    )
    if side:
        q = q.where(BulkBlockDeal.side == side)

    result = await db.execute(q)
    rows = []
    for r in result.all():
        rows.append(
            {
                "client_name_norm": r[0],
                "display_name": r[1],
                "trades": int(r[2]),
                "total_value_inr": _f(r[3]),
                "buy_value_inr": _f(r[4]),
                "sell_value_inr": _f(r[5]),
                "net_value_inr": (_f(r[4]) or 0) - (_f(r[5]) or 0),
                "is_known_shark": bool(r[6]),
                "stock_count": int(r[7]),
            }
        )
    return {"window_days": days, "since": since.isoformat(), "clients": rows}


@router.get("/sharks")
async def sharks_list(
    active_only: bool = True,
    only_with_deals: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """List tracked sharks with trade counts.

    `only_with_deals=true` filters out sharks whose matched deal_count is 0,
    keeping the UI free of dead chips."""
    from app.services.smart_money.deals import _norm_client

    q = select(KnownShark)
    if active_only:
        q = q.where(KnownShark.active.is_(True))
    result = await db.execute(q.order_by(KnownShark.display_name))
    rows = result.scalars().all()

    out = []
    for s in rows:
        norms = {_norm_client(s.canonical_name)}
        for alias in (s.aliases or []):
            norms.add(_norm_client(alias))

        cnt_q = await db.execute(
            select(func.count(BulkBlockDeal.id))
            .where(BulkBlockDeal.client_name_norm.in_(list(norms)))
        )
        deal_count = int(cnt_q.scalar_one() or 0)

        if only_with_deals and deal_count == 0:
            continue

        out.append({
            "canonical_name": s.canonical_name,
            "display_name": s.display_name,
            "aliases": s.aliases or [],
            "deal_count": deal_count,
        })

    return {"sharks": out}


@router.get("/by-fund/{scheme_code}")
async def by_fund(
    scheme_code: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Monthly holdings for an AMFI scheme — empty until AMFI monthly XLS
    ingestion ships. Stub returns a clean empty payload with a pending flag."""
    from app.models.smart_money import MfHoldingMonthly, MfScheme

    scheme_q = await db.execute(
        select(MfScheme).where(MfScheme.amfi_scheme_code == scheme_code)
    )
    scheme = scheme_q.scalar_one_or_none()
    if not scheme:
        raise HTTPException(status_code=404, detail=f"scheme {scheme_code} not found")

    holdings_q = await db.execute(
        select(MfHoldingMonthly)
        .where(MfHoldingMonthly.scheme_id == scheme.id)
        .order_by(desc(MfHoldingMonthly.report_month))
        .limit(200)
    )
    holdings = holdings_q.scalars().all()

    return {
        "scheme": {
            "amfi_scheme_code": scheme.amfi_scheme_code,
            "scheme_name": scheme.scheme_name,
            "fund_house": scheme.fund_house,
            "scheme_category": scheme.scheme_category,
            "nav": _f(scheme.nav),
            "nav_date": scheme.nav_date.isoformat() if scheme.nav_date else None,
        },
        "pending": len(holdings) == 0,
        "note": "AMFI monthly portfolio XLS ingestion pending — no holdings stored yet." if not holdings else None,
        "holdings": [
            {
                "symbol": h.symbol,
                "report_month": h.report_month.isoformat(),
                "units": _f(h.units),
                "market_value_inr": _f(h.market_value_inr),
                "pct_of_aum": _f(h.pct_of_aum),
                "change_units": _f(h.change_units),
                "change_type": h.change_type,
            }
            for h in holdings
        ],
    }


@router.get("/by-manager/{manager_id}")
async def by_manager(
    manager_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """PMS manager detail — pending PMS PDF ingestion."""
    from app.models.smart_money import PmsManager, PmsStrategyHoldingQuarterly

    mgr_q = await db.execute(select(PmsManager).where(PmsManager.id == manager_id))
    mgr = mgr_q.scalar_one_or_none()
    if not mgr:
        raise HTTPException(status_code=404, detail=f"pms manager {manager_id} not found")

    holdings_q = await db.execute(
        select(PmsStrategyHoldingQuarterly)
        .where(PmsStrategyHoldingQuarterly.manager_id == manager_id)
        .order_by(desc(PmsStrategyHoldingQuarterly.report_quarter))
        .limit(500)
    )
    holdings = holdings_q.scalars().all()

    return {
        "manager": {
            "id": mgr.id,
            "sebi_reg_no": mgr.sebi_reg_no,
            "name": mgr.name,
            "total_aum_crore": _f(mgr.total_aum_crore),
            "website": mgr.website,
        },
        "pending": len(holdings) == 0,
        "note": "SEBI PMS quarterly PDF ingestion pending — no holdings stored yet." if not holdings else None,
        "holdings": [
            {
                "strategy_name": h.strategy_name,
                "symbol": h.symbol,
                "report_quarter": h.report_quarter.isoformat(),
                "pct_of_strategy": _f(h.pct_of_strategy),
                "market_value_inr": _f(h.market_value_inr),
            }
            for h in holdings
        ],
    }


def _strip_suffix(name: str) -> str:
    """Reduce company name to the matching stem: drop Ltd / Limited /
    Private / Pvt / . / , / The — keep the identifying tokens."""
    import re as _re
    n = name.lower().strip()
    n = _re.sub(r"[.,]", " ", n)
    n = _re.sub(r"\b(limited|ltd|private|pvt|the|corporation|corp|india|company|co)\b", " ", n)
    n = _re.sub(r"\s+", " ", n).strip()
    return n


async def _resolve_symbols(db: AsyncSession, raw_symbols: set[str]) -> dict[str, str]:
    """Given raw "Stocks" values from CSVs (may be NSE tickers OR
    company names), return a map raw → NSE tradingsymbol. When no match
    is found, the raw name is passed through unchanged — so groupings
    remain stable even without resolution."""
    from app.models.stock import Stock

    out: dict[str, str] = {}
    if not raw_symbols:
        return out

    # Pass 1 — exact tradingsymbol match (for files that already use tickers)
    tickers_to_check = [s for s in raw_symbols if s and " " not in s and len(s) <= 20]
    if tickers_to_check:
        result = await db.execute(
            select(Stock.tradingsymbol)
            .where(Stock.tradingsymbol.in_(tickers_to_check))
            .where(Stock.exchange == "NSE")
        )
        for (sym,) in result.all():
            out[sym] = sym
            out[sym.upper()] = sym

    # Pass 2 — company-name match for the rest
    to_name_match = [s for s in raw_symbols if s not in out]
    if to_name_match:
        # Pull all NSE EQ stocks once — relatively small table
        result = await db.execute(
            select(Stock.tradingsymbol, Stock.name)
            .where(Stock.exchange == "NSE")
            .where(Stock.name.is_not(None))
        )
        # Build a normalized-name → tradingsymbol index
        idx: dict[str, str] = {}
        for sym, name in result.all():
            if not name:
                continue
            idx[_strip_suffix(name)] = sym

        for raw in to_name_match:
            key = _strip_suffix(raw)
            if not key:
                continue
            if key in idx:
                out[raw] = idx[key]
                continue
            # Try prefix match (e.g. "Triveni Turbine Ltd" → "triveni turbine")
            matches = [s for k, s in idx.items() if k.startswith(key) or key.startswith(k)]
            if len(matches) == 1:
                out[raw] = matches[0]

    return out


@router.post("/analyzer/upload")
async def analyzer_upload(
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Upload one or more bulk/block/insider CSVs. Returns a Signal-Grade
    report per stock per the 6-layer analyzer spec. Not persisted."""
    from app.services.smart_money.analyzer.csv_parser import parse_many
    from app.services.smart_money.analyzer.engine import analyze_deals

    if not files:
        raise HTTPException(status_code=400, detail="no files uploaded")

    blobs: list[tuple[str, bytes]] = []
    for f in files:
        name = f.filename or "unnamed.csv"
        if not name.lower().endswith((".csv", ".txt")):
            raise HTTPException(
                status_code=415,
                detail=f"{name}: unsupported file type (need .csv / .txt)",
            )
        data = await f.read()
        if len(data) > 10 * 1024 * 1024:  # 10 MB per file cap
            raise HTTPException(status_code=413, detail=f"{name}: file too large (>10MB)")
        blobs.append((name, data))

    rows, warnings = parse_many(blobs)

    # Resolve company names → NSE symbols so rows from Tickertape / similar
    # sources that carry "Triveni Turbine Ltd" roll up with NSE tickers.
    raw_syms = {r.symbol for r in rows}
    resolution = await _resolve_symbols(db, raw_syms)
    unresolved: set[str] = set()
    for r in rows:
        resolved = resolution.get(r.symbol)
        if resolved:
            r.symbol = resolved
        else:
            unresolved.add(r.symbol)
    if unresolved:
        unres_sample = ", ".join(sorted(unresolved)[:8])
        warnings.append(
            f"{len(unresolved)} stock name(s) could not be resolved to NSE ticker — "
            f"analyzed under the raw name. Examples: {unres_sample}"
        )

    report = analyze_deals(rows)
    report.files = [n for n, _ in blobs]
    report.warnings = warnings

    def _dump(sig) -> dict:
        d = asdict(sig)
        d["gross_cr"] = round(d.pop("gross_value_inr") / 1e7, 2)
        return d

    payload = {
        "window_start": report.window_start.isoformat() if report.window_start else None,
        "window_end": report.window_end.isoformat() if report.window_end else None,
        "total_rows": report.total_rows,
        "stocks_seen": report.stocks_seen,
        "files": report.files,
        "warnings": report.warnings,
        "signals": [_dump(s) for s in report.signals],
        "neutral": [_dump(s) for s in report.neutral],
        "noise": [_dump(s) for s in report.noise],
    }

    # Persist session + raw files so past analyses can be reviewed later.
    label_bits: list[str] = []
    if report.window_start and report.window_end:
        if report.window_start == report.window_end:
            label_bits.append(report.window_start.isoformat())
        else:
            label_bits.append(f"{report.window_start} → {report.window_end}")
    label_bits.append(f"{report.stocks_seen} stocks")
    label = " · ".join(label_bits) if label_bits else None

    files_meta = [
        {"filename": n, "size_bytes": len(d), "sha256": hashlib.sha256(d).hexdigest()}
        for n, d in blobs
    ]

    session = AnalyzerSession(
        user_id=user.id,
        label=label,
        window_start=report.window_start,
        window_end=report.window_end,
        total_rows=report.total_rows,
        stocks_seen=report.stocks_seen,
        signal_count=len(report.signals),
        neutral_count=len(report.neutral),
        noise_count=len(report.noise),
        files_meta=files_meta,
        report_json=payload,
    )
    db.add(session)
    await db.flush()

    for fm, (name, data) in zip(files_meta, blobs):
        db.add(AnalyzerSessionFile(
            session_id=session.id,
            filename=name,
            size_bytes=fm["size_bytes"],
            sha256=fm["sha256"],
            content=data,
        ))
    await db.commit()

    payload["session_id"] = session.id
    payload["session_created_at"] = session.created_at.isoformat() if session.created_at else None
    return payload


@router.get("/analyzer/sessions")
async def analyzer_sessions_list(
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    q = (
        select(AnalyzerSession)
        .where(AnalyzerSession.user_id == user.id)
        .order_by(desc(AnalyzerSession.created_at))
        .limit(limit)
    )
    result = await db.execute(q)
    sessions = result.scalars().all()
    return {
        "sessions": [
            {
                "id": s.id,
                "label": s.label,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "window_start": s.window_start.isoformat() if s.window_start else None,
                "window_end": s.window_end.isoformat() if s.window_end else None,
                "total_rows": s.total_rows,
                "stocks_seen": s.stocks_seen,
                "signal_count": s.signal_count,
                "neutral_count": s.neutral_count,
                "noise_count": s.noise_count,
                "files_meta": s.files_meta or [],
            }
            for s in sessions
        ]
    }


@router.get("/analyzer/sessions/{session_id}")
async def analyzer_session_detail(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    s = await db.get(AnalyzerSession, session_id)
    if not s or s.user_id != user.id:
        raise HTTPException(status_code=404, detail="session not found")
    payload = dict(s.report_json or {})
    payload["session_id"] = s.id
    payload["session_created_at"] = s.created_at.isoformat() if s.created_at else None
    payload["label"] = s.label
    return payload


@router.get("/analyzer/sessions/{session_id}/files/{file_id}")
async def analyzer_session_file(
    session_id: int,
    file_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    s = await db.get(AnalyzerSession, session_id)
    if not s or s.user_id != user.id:
        raise HTTPException(status_code=404, detail="session not found")
    f = await db.get(AnalyzerSessionFile, file_id)
    if not f or f.session_id != session_id:
        raise HTTPException(status_code=404, detail="file not found")
    return Response(
        content=bytes(f.content),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{f.filename}"'},
    )


@router.delete("/analyzer/sessions/{session_id}")
async def analyzer_session_delete(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    s = await db.get(AnalyzerSession, session_id)
    if not s or s.user_id != user.id:
        raise HTTPException(status_code=404, detail="session not found")
    await db.delete(s)
    await db.commit()
    return {"deleted": session_id}




# ---- Spec §12: new endpoints (PR 4) ----------------------------------------


def _serialize_insider(row) -> dict:
    return {
        "id": row.id,
        "symbol": row.symbol,
        "person_name": row.person_name,
        "category": row.category,
        "transaction_type": row.transaction_type,
        "shares": row.shares,
        "value_inr": _f(row.value_inr),
        "transaction_date": row.transaction_date.isoformat() if row.transaction_date else None,
        "intimation_date": row.intimation_date.isoformat() if row.intimation_date else None,
        "mode": row.mode,
        "pre_holding_pct": _f(row.pre_holding_pct),
        "post_holding_pct": _f(row.post_holding_pct),
        "exchange": row.exchange,
        "is_known_shark": row.is_known_shark,
    }


def _serialize_announcement(row) -> dict:
    return {
        "id": row.id,
        "symbol": row.symbol,
        "announcement_type": row.announcement_type,
        "headline": row.headline,
        "buyback_size_inr": _f(row.buyback_size_inr),
        "buyback_price_inr": _f(row.buyback_price_inr),
        "pledge_shares": int(row.pledge_shares) if row.pledge_shares is not None else None,
        "pledge_pct_of_holding": _f(row.pledge_pct_of_holding),
        "pledge_direction": row.pledge_direction,
        "pledgor_name": row.pledgor_name,
        "announcement_date": row.announcement_date.isoformat() if row.announcement_date else None,
        "exchange": row.exchange,
    }


def _serialize_shp(row) -> dict:
    return {
        "id": row.id,
        "symbol": row.symbol,
        "quarter": row.quarter,
        "quarter_end_date": row.quarter_end_date.isoformat(),
        "promoter_pct": _f(row.promoter_pct),
        "promoter_pledge_pct": _f(row.promoter_pledge_pct),
        "fii_pct": _f(row.fii_pct),
        "dii_pct": _f(row.dii_pct),
        "mf_pct": _f(row.mf_pct),
        "insurance_pct": _f(row.insurance_pct),
        "public_pct": _f(row.public_pct),
        "promoter_delta": _f(row.promoter_delta),
        "fii_delta": _f(row.fii_delta),
        "dii_delta": _f(row.dii_delta),
        "pledge_delta": _f(row.pledge_delta),
    }


def _serialize_net_pos(row) -> dict:
    return {
        "party_name_norm": row.party_name_norm,
        "party_category": row.party_category,
        "net_shares": int(row.net_shares),
        "net_value_inr": _f(row.net_value_inr),
        "distinct_buy_days": row.distinct_buy_days,
        "distinct_sell_days": row.distinct_sell_days,
        "is_known_shark": row.is_known_shark,
        "is_circular_suspect": row.is_circular_suspect,
    }


@router.get("/insider-activity")
async def insider_activity(
    symbol: str | None = Query(default=None),
    category: str | None = Query(default=None),
    transaction_type: str | None = Query(default=None),
    days: int = Query(default=30, le=365),
    limit: int = Query(default=100, le=500),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Paginated insider-disclosures feed. All filters optional."""
    from app.models.smart_money import InsiderDisclosure

    since = datetime.now().date() - timedelta(days=days)
    q = select(InsiderDisclosure).where(InsiderDisclosure.transaction_date >= since)
    if symbol:
        q = q.where(InsiderDisclosure.symbol == symbol.upper().strip())
    if category:
        q = q.where(InsiderDisclosure.category == category)
    if transaction_type:
        q = q.where(InsiderDisclosure.transaction_type == transaction_type)
    q = q.order_by(desc(InsiderDisclosure.transaction_date), desc(InsiderDisclosure.id)).limit(limit)
    result = await db.execute(q)
    return {"rows": [_serialize_insider(r) for r in result.scalars().all()]}


@router.get("/insider-activity/{symbol}")
async def insider_for_symbol(
    symbol: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """All insider disclosures for one symbol over the last 12 months."""
    from app.models.smart_money import InsiderDisclosure

    since = datetime.now().date() - timedelta(days=365)
    q = await db.execute(
        select(InsiderDisclosure)
        .where(
            InsiderDisclosure.symbol == symbol.upper().strip(),
            InsiderDisclosure.transaction_date >= since,
        )
        .order_by(desc(InsiderDisclosure.transaction_date))
    )
    return {
        "symbol": symbol.upper().strip(),
        "rows": [_serialize_insider(r) for r in q.scalars().all()],
    }


@router.post("/shareholding/{symbol}/refresh")
async def refresh_shareholding(
    symbol: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Re-fetch NSE XBRL shareholding for a single symbol and persist."""
    from app.services.smart_money.shareholding_pattern import (
        _fetch_nse_shareholding, _persist_with_deltas,
        REQUEST_TIMEOUT,
    )
    from app.services.smart_money.insider_disclosures import HEADERS as NSE_HEADERS

    import httpx

    sym = symbol.upper().strip()
    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT, headers=NSE_HEADERS, follow_redirects=True,
    ) as client:
        try:
            await client.get("https://www.nseindia.com", timeout=15)
        except Exception:
            pass

        row = await _fetch_nse_shareholding(sym, None, client)

    if not row:
        raise HTTPException(404, f"No NSE shareholding filing found for {sym}")

    inserted, _, skipped = await _persist_with_deltas([row])
    return {"symbol": sym, "inserted": inserted, "skipped": skipped, "quarter": row.get("quarter")}


@router.get("/shareholding/{symbol}")
async def shareholding_history(
    symbol: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Quarterly shareholding pattern for one symbol, newest first."""
    from app.models.smart_money import ShareholdingPattern

    q = await db.execute(
        select(ShareholdingPattern)
        .where(ShareholdingPattern.symbol == symbol.upper().strip())
        .order_by(desc(ShareholdingPattern.quarter_end_date))
        .limit(20)
    )
    return {
        "symbol": symbol.upper().strip(),
        "rows": [_serialize_shp(r) for r in q.scalars().all()],
    }


@router.get("/red-flags")
async def red_flags(
    flag_type: str | None = Query(default=None),
    min_severity: int = Query(default=20, ge=0, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """All stocks with active red flags. `min_severity` is the absolute
    penalty threshold — flags below it are filtered out. Optionally
    restrict to a specific flag type (circular_trading / pump_pattern /
    promoter_selling / high_pledge / pledge_invocation)."""
    latest_q = await db.execute(select(func.max(SmartMoneySignal.as_of)))
    latest = latest_q.scalar_one_or_none()
    if not latest:
        return {"as_of": None, "rows": []}

    rows = await db.execute(
        select(SmartMoneySignal)
        .where(
            SmartMoneySignal.as_of == latest,
            SmartMoneySignal.red_flag_score.is_not(None),
            SmartMoneySignal.red_flag_score <= -min_severity,
        )
        .order_by(SmartMoneySignal.red_flag_score.asc())
        .limit(200)
    )

    out = []
    for sig in rows.scalars().all():
        breakdown = sig.signal_breakdown or {}
        triggered = (breakdown.get("red_flags") or {}).get("triggered") or []
        if flag_type and flag_type not in triggered:
            continue
        out.append({
            "symbol": sig.symbol,
            "red_flag_score": _f(sig.red_flag_score),
            "triggered": triggered,
            "detail": (breakdown.get("red_flags") or {}).get("detail") or {},
        })
    return {"as_of": latest.isoformat(), "rows": out}


@router.get("/net-positions/{symbol}")
async def net_positions_for_symbol(
    symbol: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """30-day net positions per party for one stock, newest rollup."""
    from app.models.smart_money import NetPosition30d

    latest_q = await db.execute(
        select(func.max(NetPosition30d.as_of)).where(NetPosition30d.symbol == symbol.upper().strip())
    )
    latest = latest_q.scalar_one_or_none()
    if not latest:
        return {"symbol": symbol.upper().strip(), "as_of": None, "rows": []}
    q = await db.execute(
        select(NetPosition30d)
        .where(
            NetPosition30d.symbol == symbol.upper().strip(),
            NetPosition30d.as_of == latest,
        )
        .order_by(desc(NetPosition30d.net_value_inr))
    )
    return {
        "symbol": symbol.upper().strip(),
        "as_of": latest.isoformat(),
        "rows": [_serialize_net_pos(r) for r in q.scalars().all()],
    }


@router.get("/announcements")
async def announcements_feed(
    type: str | None = Query(default=None, alias="type"),
    days: int = Query(default=30, le=365),
    limit: int = Query(default=100, le=500),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Corporate-announcements feed (buybacks + pledges)."""
    from app.models.smart_money import CorporateAnnouncement

    since = datetime.now().date() - timedelta(days=days)
    q = select(CorporateAnnouncement).where(CorporateAnnouncement.announcement_date >= since)
    if type:
        q = q.where(CorporateAnnouncement.announcement_type == type.upper())
    q = q.order_by(desc(CorporateAnnouncement.announcement_date)).limit(limit)
    result = await db.execute(q)
    return {"rows": [_serialize_announcement(r) for r in result.scalars().all()]}


@router.get("/fii-dii/{symbol}")
async def fii_dii_for_symbol(
    symbol: str,
    days: int = Query(default=30, le=365),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Stock-level FII/DII daily history (sparse — see service docstring)."""
    from app.models.smart_money import FiiDiiStockDaily

    since = datetime.now().date() - timedelta(days=days)
    q = await db.execute(
        select(FiiDiiStockDaily)
        .where(
            FiiDiiStockDaily.symbol == symbol.upper().strip(),
            FiiDiiStockDaily.trade_date >= since,
        )
        .order_by(FiiDiiStockDaily.trade_date)
    )
    return {
        "symbol": symbol.upper().strip(),
        "rows": [
            {
                "trade_date": r.trade_date.isoformat(),
                "fii_buy": _f(r.fii_buy_value),
                "fii_sell": _f(r.fii_sell_value),
                "fii_net": _f(r.fii_net_value),
                "dii_buy": _f(r.dii_buy_value),
                "dii_sell": _f(r.dii_sell_value),
                "dii_net": _f(r.dii_net_value),
            }
            for r in q.scalars().all()
        ],
    }


@router.get("/score-breakdown/{symbol}")
async def score_breakdown(
    symbol: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Full conviction / flow / red-flag breakdown for one stock — the
    raw signal_breakdown JSON written by the rollup. Used by the
    SmartMoneyPanel signal-breakdown accordion."""
    sig_q = await db.execute(
        select(SmartMoneySignal)
        .where(SmartMoneySignal.symbol == symbol.upper().strip())
        .order_by(desc(SmartMoneySignal.as_of))
        .limit(1)
    )
    sig = sig_q.scalar_one_or_none()
    if not sig:
        return {"symbol": symbol.upper().strip(), "as_of": None, "breakdown": None}
    return {
        "symbol": sig.symbol,
        "as_of": sig.as_of.isoformat(),
        "conviction_score": _f(sig.conviction_score),
        "flow_score": _f(sig.flow_score),
        "red_flag_score": _f(sig.red_flag_score),
        "composite": _f(sig.composite),
        "breakdown": sig.signal_breakdown,
    }


# ---- Addendum A2b: action summary -----------------------------------------


@router.get("/action-summary")
async def action_summary(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """The three-card summary at the top of /smart-money — what the user
    needs to look at today. Single round-trip so the page renders fast.

    Each card surfaces a *headline signal* (the single most important
    reason this stock is here) plus a confirming line. Cap at 5 stocks
    per card — this is daily-action, not a screener dump.

    Selection rules per spec §A2b:
      ACCUMULATION — composite conviction ≥ 30 AND red_flag > -30.
      DISTRIBUTION — composite conviction ≤ -30.
      AVOID — red_flag ≤ -25 (most negative first).
    Stocks where the signal is driven entirely by intra-group transfers
    are already excluded by the rollup (PR 6 / addendum A1a).
    """
    from app.models.smart_money import InsiderDisclosure

    latest_q = await db.execute(select(func.max(SmartMoneySignal.as_of)))
    as_of = latest_q.scalar_one_or_none()
    if not as_of:
        return {"as_of": None, "accumulation": [], "distribution": [], "avoid": []}

    # ---- Accumulation
    acc_q = await db.execute(
        select(SmartMoneySignal)
        .where(
            SmartMoneySignal.as_of == as_of,
            SmartMoneySignal.conviction_score.is_not(None),
            SmartMoneySignal.conviction_score >= 30,
            (SmartMoneySignal.red_flag_score.is_(None))
            | (SmartMoneySignal.red_flag_score > -30),
        )
        .order_by(desc(SmartMoneySignal.conviction_score))
        .limit(5)
    )
    accumulation = [_summarise_signal(s, "accumulation") for s in acc_q.scalars().all()]

    # ---- Distribution
    dist_q = await db.execute(
        select(SmartMoneySignal)
        .where(
            SmartMoneySignal.as_of == as_of,
            SmartMoneySignal.conviction_score.is_not(None),
            SmartMoneySignal.conviction_score <= -30,
        )
        .order_by(SmartMoneySignal.conviction_score.asc())
        .limit(5)
    )
    distribution = [_summarise_signal(s, "distribution") for s in dist_q.scalars().all()]

    # ---- Avoid (red flags)
    avoid_q = await db.execute(
        select(SmartMoneySignal)
        .where(
            SmartMoneySignal.as_of == as_of,
            SmartMoneySignal.red_flag_score.is_not(None),
            SmartMoneySignal.red_flag_score <= -25,
        )
        .order_by(SmartMoneySignal.red_flag_score.asc())
        .limit(5)
    )
    avoid = [_summarise_signal(s, "avoid") for s in avoid_q.scalars().all()]

    return {
        "as_of": as_of.isoformat(),
        "accumulation": accumulation,
        "distribution": distribution,
        "avoid": avoid,
    }


def _summarise_signal(sig: SmartMoneySignal, card_type: str) -> dict:
    """One row in an action-summary card. The headline + confirmation
    lines explain *why* this stock is on the card so the user doesn't
    have to dig into the breakdown to decide whether to act.
    """
    breakdown = sig.signal_breakdown or {}
    conv = breakdown.get("conviction") or {}
    flow = breakdown.get("flow") or {}
    rf = breakdown.get("red_flags") or {}

    headline = ""
    confirm = ""

    if card_type == "accumulation":
        # Pick the strongest available conviction sub-signal.
        pb = conv.get("promoter_buying") or {}
        sa = conv.get("shark_accumulation") or {}
        mc = conv.get("mf_consensus") or {}
        if pb.get("raw"):
            headline = f"Promoter open-market buying: {int(pb['raw']):,} shares"
        elif sa.get("raw"):
            headline = f"Tracked-investor accumulation: {sa.get('source_rows', 0)} party(ies)"
        elif mc.get("raw"):
            headline = f"MF consensus: {mc.get('increased', 0)} houses adding"
        # Confirming flow signal
        dlv = flow.get("delivery") or {}
        if dlv.get("recent_avg") and dlv.get("baseline_avg"):
            confirm = f"Delivery 5d {dlv['recent_avg']}% vs baseline {dlv['baseline_avg']}%"
    elif card_type == "distribution":
        rf_t = rf.get("triggered") or []
        if "promoter_selling" in rf_t:
            d = (rf.get("detail") or {}).get("promoter_selling") or {}
            headline = f"Promoter selling: {int(d.get('shares_sold', 0)):,} shares (90d net)"
        else:
            sa = conv.get("shark_accumulation") or {}
            if sa.get("raw") and sa["raw"] < 0:
                headline = "Tracked investors net sellers"
    elif card_type == "avoid":
        triggered = rf.get("triggered") or []
        detail = rf.get("detail") or {}
        if triggered:
            t0 = triggered[0]
            label_map = {
                "circular_trading": "Circular trading suspected",
                "pump_pattern": "Pump pattern detected",
                "promoter_selling": "Promoter selling",
                "high_pledge": "High promoter pledge",
                "pledge_invocation": "Pledge invocation",
            }
            headline = label_map.get(t0, t0.replace("_", " "))
            d = detail.get(t0) or {}
            if t0 == "high_pledge" and d.get("pledge_pct"):
                confirm = f"{d['pledge_pct']}% pledged ({d.get('quarter', '?')})"
            elif t0 == "circular_trading" and d.get("suspects"):
                confirm = f"Suspects: {', '.join(d['suspects'][:2])}"
            elif t0 == "pump_pattern" and d.get("pct_change_20d"):
                confirm = f"+{d['pct_change_20d']}% in 20d, delivery declining"

    return {
        "symbol": sig.symbol,
        "conviction_score": _f(sig.conviction_score),
        "flow_score": _f(sig.flow_score),
        "red_flag_score": _f(sig.red_flag_score),
        "composite": _f(sig.composite),
        "headline": headline,
        "confirm": confirm,
    }


@router.get("/notable-insider")
async def notable_insider(
    days: int = Query(default=14, le=90),
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Filtered insider feed for the daily-action view.

    Excludes intra-group transfers (addendum A1a) and noise (small
    designated-person trades, low-value 'Other' sales). Returns the
    rows the addendum's "Insider Activity" expandable section needs.
    """
    from app.models.smart_money import InsiderDisclosure

    since = datetime.now().date() - timedelta(days=days)
    q = await db.execute(
        select(InsiderDisclosure)
        .where(
            InsiderDisclosure.transaction_date >= since,
            InsiderDisclosure.is_intra_group_transfer.is_(False),
        )
        .order_by(desc(InsiderDisclosure.transaction_date), desc(InsiderDisclosure.id))
        .limit(limit * 2)  # over-fetch; filter in Python
    )
    rows = list(q.scalars().all())

    out: list[dict] = []
    for r in rows:
        # Notable-filter rules from addendum §A2c:
        #   - any promoter open-market buy (always notable)
        #   - any pledge action
        #   - designated person buy ≥ ₹10L value
        #   - "Other" sale ≥ ₹50L value (otherwise exclude)
        value = float(r.value_inr) if r.value_inr is not None else 0.0
        keep = False
        if r.category in ("Promoter", "Promoter Group"):
            keep = True
        elif r.transaction_type in ("Pledge", "Revoke", "Invoke"):
            keep = True
        elif r.category == "Designated Person" and r.transaction_type == "Buy" and value >= 1_000_000:
            keep = True
        elif r.category == "Other" and r.transaction_type == "Sale" and value >= 5_000_000:
            keep = True
        if not keep:
            continue

        # Strength bucket
        if value >= 50_000_000:
            strength = "strong"
        elif value >= 5_000_000:
            strength = "moderate"
        else:
            strength = "minor"

        out.append({
            "id": r.id,
            "symbol": r.symbol,
            "person_name": r.person_name,
            "category": r.category,
            "transaction_type": r.transaction_type,
            "shares": r.shares,
            "value_inr": _f(r.value_inr),
            "transaction_date": r.transaction_date.isoformat() if r.transaction_date else None,
            "mode": r.mode,
            "strength": strength,
        })
        if len(out) >= limit:
            break

    return {"as_of": datetime.now().date().isoformat(), "rows": out}


@router.get("/net-traders")
async def net_traders(
    days: int = Query(default=30, le=90),
    show_brokers: bool = Query(default=False),
    min_ratio: float = Query(default=0.2, ge=0.0, le=1.0),
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Active traders who actually took a directional position.

    Sorted by abs(net_buy) descending — gross volume isn't the metric;
    a ₹1465 Cr trader who netted -₹45L is noise. The `min_ratio`
    parameter (default 0.2) drops anyone whose |net|/gross is below the
    threshold — they're squaring off, not betting. PROP_HFT and BROKER
    categories are hidden by default; toggle `show_brokers=true` to
    include them.
    """
    since = datetime.now().date() - timedelta(days=days)

    # Aggregate per-client across all symbols
    cols = (
        BulkBlockDeal.client_name_norm,
        BulkBlockDeal.client_name_raw,
        BulkBlockDeal.client_category,
        BulkBlockDeal.is_known_shark,
        func.count(BulkBlockDeal.id).label("trades"),
        func.count(func.distinct(BulkBlockDeal.symbol)).label("stock_count"),
        func.sum(case((BulkBlockDeal.side == "BUY", BulkBlockDeal.trade_value_inr), else_=0)).label("buy_v"),
        func.sum(case((BulkBlockDeal.side == "SELL", BulkBlockDeal.trade_value_inr), else_=0)).label("sell_v"),
        func.sum(BulkBlockDeal.trade_value_inr).label("total_v"),
    )
    q = select(*cols).where(BulkBlockDeal.trade_date >= since).group_by(
        BulkBlockDeal.client_name_norm,
        BulkBlockDeal.client_name_raw,
        BulkBlockDeal.client_category,
        BulkBlockDeal.is_known_shark,
    )
    if not show_brokers:
        q = q.where(
            BulkBlockDeal.client_category.notin_(("PROP_HFT", "BROKER"))
            | BulkBlockDeal.client_category.is_(None)
        )

    result = await db.execute(q)
    rows = []
    for r in result.all():
        buy = _f(r.buy_v) or 0.0
        sell = _f(r.sell_v) or 0.0
        total = _f(r.total_v) or 0.0
        net = buy - sell
        if total <= 0:
            continue
        ratio = abs(net) / total
        if ratio < min_ratio:
            continue
        rows.append({
            "client_name_norm": r.client_name_norm,
            "display_name": r.client_name_raw,
            "client_category": r.client_category,
            "is_known_shark": r.is_known_shark,
            "trades": r.trades,
            "stock_count": r.stock_count,
            "buy_value_inr": buy,
            "sell_value_inr": sell,
            "net_value_inr": net,
            "total_value_inr": total,
            "net_to_total_ratio": round(ratio, 3),
        })

    rows.sort(key=lambda x: abs(x["net_value_inr"]), reverse=True)

    # Apply user-level category overrides (addendum §A2e). Overrides
    # take precedence over the heuristic classifier so the user can
    # teach the system per-client.
    from app.models.smart_money import ClientOverride

    override_q = await db.execute(
        select(ClientOverride.client_name_norm, ClientOverride.override_category)
        .where(ClientOverride.user_id == user.id)
    )
    overrides = {n: c for n, c in override_q.all()}
    if overrides:
        for r in rows:
            if r["client_name_norm"] in overrides:
                r["client_category"] = overrides[r["client_name_norm"]]
                r["category_overridden"] = True

    return {"window_days": days, "rows": rows[:limit]}


# ---- Addendum §A2e: client overrides --------------------------------------

from pydantic import BaseModel, Field  # noqa: E402


class ClientOverrideBody(BaseModel):
    client_name_norm: str = Field(min_length=1, max_length=255)
    override_category: str = Field(min_length=1, max_length=30)
    notes: str | None = None


@router.put("/client-override")
async def upsert_client_override(
    body: ClientOverrideBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Insert or update the user's category override for a client.

    The classifier reads `client_overrides` first when scoring, so this
    is the user-facing knob for "AUTHUM INVESTMENT is actually a fund,
    not CORP_OTHER." Categories must match the 9 enum values from
    party_classifier.py.
    """
    from app.models.smart_money import ClientOverride
    from app.services.smart_money.analyzer import party_classifier as pc

    valid_categories = {
        pc.QUALITY_MF_FPI, pc.VC_PE, pc.PROMOTER, pc.INSIDER_OTHER,
        pc.PROP_HFT, pc.OTHER_FUND, pc.BROKER, pc.CORP_OTHER, pc.INDIVIDUAL,
    }
    if body.override_category not in valid_categories:
        raise HTTPException(400, f"Invalid category. Must be one of {sorted(valid_categories)}")

    norm = body.client_name_norm.strip().lower()

    existing_q = await db.execute(
        select(ClientOverride).where(
            ClientOverride.user_id == user.id,
            ClientOverride.client_name_norm == norm,
        )
    )
    existing = existing_q.scalar_one_or_none()
    if existing is not None:
        existing.override_category = body.override_category
        existing.notes = body.notes
    else:
        db.add(
            ClientOverride(
                user_id=user.id,
                client_name_norm=norm,
                override_category=body.override_category,
                notes=body.notes,
            )
        )
    await db.commit()
    return {"status": "ok", "client_name_norm": norm, "override_category": body.override_category}


@router.delete("/client-override/{client_name_norm}")
async def delete_client_override(
    client_name_norm: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Remove a per-user override; classifier falls back to heuristics."""
    from app.models.smart_money import ClientOverride

    existing_q = await db.execute(
        select(ClientOverride).where(
            ClientOverride.user_id == user.id,
            ClientOverride.client_name_norm == client_name_norm.strip().lower(),
        )
    )
    existing = existing_q.scalar_one_or_none()
    if existing is None:
        raise HTTPException(404, "Override not found")
    await db.delete(existing)
    await db.commit()
    return {"status": "deleted"}


@router.get("/client-overrides")
async def list_client_overrides(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """List the calling user's active overrides."""
    from app.models.smart_money import ClientOverride

    q = await db.execute(
        select(ClientOverride).where(ClientOverride.user_id == user.id)
        .order_by(ClientOverride.client_name_norm)
    )
    return {
        "rows": [
            {
                "client_name_norm": o.client_name_norm,
                "override_category": o.override_category,
                "notes": o.notes,
                "created_at": o.created_at.isoformat() if o.created_at else None,
            }
            for o in q.scalars().all()
        ]
    }


# ---- PR 10: coverage diagnostic + holdings signal --------------------------


# Tradingsymbol prefixes (Kite naming) for non-equity instruments that may
# appear in the holdings call but have no equity smart-money signal — sovereign
# gold bonds, exchange-traded gold, T-bills/G-secs. Listed here rather than
# relying on `instrument_type` because Kite's holdings response doesn't
# include instrument_type — only tradingsymbol, exchange, segment.
_NON_EQUITY_PREFIXES = ("SGB", "SGBNOV", "SGBSEP", "SGBOCT", "SGBJUL", "SGBJUN", "SGBAUG", "SGBDEC", "SGBJAN", "SGBFEB", "SGBMAR", "SGBAPR", "SGBMAY")
_NON_EQUITY_SUFFIXES = ("-GB",)


def _is_non_equity(symbol: str) -> bool:
    """Heuristic for bonds / gold / non-equity holdings that should not be
    scored against equity smart-money signals (insider trades, bulk deals,
    institutional flows). Matches SGB* sovereign gold bonds and the `-GB`
    suffix convention used for some bond listings."""
    if not symbol:
        return False
    s = symbol.upper()
    if any(s.startswith(p) for p in _NON_EQUITY_PREFIXES):
        return True
    if any(s.endswith(suf) for suf in _NON_EQUITY_SUFFIXES):
        return True
    return False


@router.get("/holdings-signals")
async def holdings_signals(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Per-holding smart-money signal — ADD / HOLD / TRIM / REVIEW / NO_SIGNAL.

    Iterates the user's live Kite holdings (via portfolio_cache) and
    returns one signal row per stock plus the union of holdings + the
    SmartMoneyHoldingsTable can render. NO_SIGNAL rows are surfaced
    explicitly so the user can see which holdings have thin coverage.

    Sovereign Gold Bonds and other non-equity instruments are filtered out
    of the scored rows and surfaced separately under `non_equity` so the
    user knows we're aware of them but they don't get a spurious
    direction.
    """
    from app.services.portfolio_cache import get_holdings as cached_holdings
    from app.services.smart_money.holdings_signal import compute_holding_signal

    try:
        holdings = await cached_holdings(user)
    except Exception:
        holdings = []

    rows: list[dict] = []
    non_equity: list[dict] = []
    for h in holdings:
        sym = (h.get("tradingsymbol") or "").upper().strip()
        if not sym or h.get("quantity", 0) <= 0:
            continue
        if _is_non_equity(sym):
            non_equity.append({
                "symbol": sym,
                "quantity": h.get("quantity"),
                "average_price": h.get("average_price"),
                "last_price": h.get("last_price"),
                "kind": "bond",
            })
            continue
        try:
            sig = await compute_holding_signal(sym, db, user.id)
            row = sig.to_dict()
            row["quantity"] = h.get("quantity")
            row["average_price"] = h.get("average_price")
            row["last_price"] = h.get("last_price")
            rows.append(row)
        except Exception:
            # Don't let a single symbol failure kill the whole list.
            rows.append({
                "symbol": sym,
                "direction": "NO_SIGNAL",
                "confidence": "LOW",
                "headline": "Signal compute failed",
                "drivers": [],
                "coverage_score": 0,
            })

    # NO_SIGNAL first (per the spec: highlight when a holding lacks data),
    # then REVIEW (red flags), then ADD/TRIM with strongest signal first,
    # then HOLD. Within direction, descending by coverage so the best-
    # supported reads sort first.
    direction_order = {"NO_SIGNAL": 0, "REVIEW": 1, "ADD": 2, "TRIM": 3, "HOLD": 4}
    rows.sort(key=lambda r: (
        direction_order.get(r.get("direction"), 5),
        -(r.get("coverage_score") or 0),
    ))

    counts = {d: 0 for d in direction_order}
    for r in rows:
        counts[r["direction"]] = counts.get(r["direction"], 0) + 1

    return {"rows": rows, "counts": counts, "non_equity": non_equity}


@router.get("/coverage/{symbol}")
async def coverage(
    symbol: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Per-source data-availability summary for a symbol.

    Used by the SmartMoneyPanel to render a "limited data" callout
    when score < 50, and by the holdings-signal layer to short-circuit
    to NO_SIGNAL on thin coverage rather than producing misleading
    output. See `services/smart_money/coverage.py` for weights.
    """
    from app.services.smart_money.coverage import compute_coverage

    cov = await compute_coverage(symbol, db)
    return cov.to_dict()


@router.get("/{symbol}")
async def per_stock(
    symbol: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Per-stock SmartMoneyPanel data: latest signal + raw deals + delivery trend."""
    symbol = symbol.upper().strip()

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
    deals = [_serialize_deal(d) for d in deals_q.scalars().all()]

    bhav_since = datetime.now().date() - timedelta(days=60)
    bhav_q = await db.execute(
        select(BhavcopyDaily)
        .where(BhavcopyDaily.symbol == symbol, BhavcopyDaily.trade_date >= bhav_since)
        .order_by(BhavcopyDaily.trade_date)
    )
    delivery_trend = [
        {
            "trade_date": b.trade_date.isoformat(),
            "close_price": _f(b.close_price),
            "traded_qty": int(b.traded_qty) if b.traded_qty is not None else None,
            "delivery_pct": _f(b.delivery_pct),
            "turnover_inr": _f(b.turnover_inr),
        }
        for b in bhav_q.scalars().all()
    ]

    return {
        "symbol": symbol,
        "signal": _serialize_signal(sig) if sig else None,
        "deals_last_30d": deals,
        "delivery_trend": delivery_trend,
    }
