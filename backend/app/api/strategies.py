from fastapi import APIRouter, Depends, HTTPException
from kiteconnect import KiteConnect
from pydantic import BaseModel
from sqlalchemy import and_, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.strategy import Strategy
from app.models.strategy_run import StrategyRun
from app.models.user import User
from app.models.watchlist import Watchlist, WatchlistItem
from app.services.default_strategies import DEFAULT_STRATEGIES
from app.services.nifty50 import NIFTY_50
from app.services.strategy_runner import run_strategy_on_symbols

router = APIRouter()


VALID_STRATEGY_TYPES = {"value", "growth", "quality", "momentum", "dividend", "custom"}

VALID_FILTER_KEYS = {
    "pe_ratio_max", "pb_ratio_max", "forward_pe_max", "ttm_pe_max",
    "debt_to_equity_max", "net_profit_margin_min", "roe_min",
    "revenue_growth_1y_min", "eps_growth_1y_min", "earnings_growth_forward_min",
    "dividend_yield_min", "promoter_holding_min", "near_52w_high_pct",
    "market_cap_min_cr", "market_cap_max_cr",
}

VALID_WEIGHT_KEYS = {
    "pe", "pb", "forward_pe", "roe", "margin", "debt",
    "revenue_growth", "eps_growth", "growth", "dividend_yield",
    "promoter_holding", "near_52w_high",
}


def _validate_config(cfg: dict) -> None:
    filters = cfg.get("filters", {})
    weights = cfg.get("weights", {})
    for k in filters:
        if k not in VALID_FILTER_KEYS:
            raise HTTPException(status_code=422, detail=f"Unknown filter key: {k}")
        if not isinstance(filters[k], (int, float)):
            raise HTTPException(status_code=422, detail=f"Filter '{k}' must be numeric")
    for k in weights:
        if k not in VALID_WEIGHT_KEYS:
            raise HTTPException(status_code=422, detail=f"Unknown weight key: {k}")
        if not isinstance(weights[k], (int, float)):
            raise HTTPException(status_code=422, detail=f"Weight '{k}' must be numeric")


class CreateStrategyRequest(BaseModel):
    name: str
    description: str | None = None
    strategy_type: str = "custom"
    config_json: dict


class UpdateStrategyRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    strategy_type: str | None = None
    config_json: dict | None = None


class ImportRequest(BaseModel):
    strategy_ids: list[int]


class RunStrategyRequest(BaseModel):
    target_type: str  # holdings | watchlist | nifty50
    watchlist_id: int | None = None


@router.get("/")
async def list_strategies(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(Strategy).where(
            or_(
                and_(Strategy.user_id.is_(None), Strategy.is_default.is_(True)),
                Strategy.user_id == user.id,
            )
        )
    )
    strategies = result.scalars().all()

    defaults = []
    user_strategies = []
    for s in strategies:
        data = {
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "strategy_type": s.strategy_type,
            "is_default": s.is_default,
            "is_active": s.is_active,
            "config_json": s.config_json,
            "is_mine": s.user_id == user.id,
        }
        if s.is_default and s.user_id is None:
            defaults.append(data)
        else:
            user_strategies.append(data)

    return {"defaults": defaults, "mine": user_strategies}


@router.post("/seed-defaults")
async def seed_default_strategies(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    result = await db.execute(
        select(Strategy).where(Strategy.is_default.is_(True), Strategy.user_id.is_(None))
    )
    existing = {s.name for s in result.scalars().all()}

    added = 0
    for s in DEFAULT_STRATEGIES:
        if s["name"] in existing:
            continue
        db.add(Strategy(
            user_id=None,
            name=s["name"],
            description=s["description"],
            strategy_type=s["strategy_type"],
            config_json=s["config_json"],
            is_default=True,
            is_active=True,
        ))
        added += 1

    await db.commit()
    return {"added": added, "total_defaults": len(DEFAULT_STRATEGIES)}


@router.post("/import")
async def import_strategies(
    body: ImportRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(Strategy).where(
            Strategy.id.in_(body.strategy_ids),
            Strategy.is_default.is_(True),
            Strategy.user_id.is_(None),
        )
    )
    to_import = result.scalars().all()

    imported = []
    for s in to_import:
        existing_check = await db.execute(
            select(Strategy).where(
                Strategy.user_id == user.id,
                Strategy.name == s.name,
            )
        )
        if existing_check.scalar_one_or_none():
            continue

        db.add(Strategy(
            user_id=user.id,
            name=s.name,
            description=s.description,
            strategy_type=s.strategy_type,
            config_json=s.config_json,
            is_default=False,
            is_active=True,
        ))
        imported.append(s.name)

    await db.commit()
    return {"imported": imported, "count": len(imported)}


@router.post("/create")
async def create_strategy(
    body: CreateStrategyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if body.strategy_type not in VALID_STRATEGY_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid strategy_type: {body.strategy_type}")
    if not body.name or len(body.name.strip()) < 2:
        raise HTTPException(status_code=422, detail="Name must be at least 2 characters")
    _validate_config(body.config_json)

    strategy = Strategy(
        user_id=user.id,
        name=body.name.strip(),
        description=(body.description or "").strip() or None,
        strategy_type=body.strategy_type,
        config_json=body.config_json,
        is_default=False,
        is_active=True,
    )
    db.add(strategy)
    await db.commit()
    await db.refresh(strategy)
    return {
        "id": strategy.id,
        "name": strategy.name,
        "description": strategy.description,
        "strategy_type": strategy.strategy_type,
        "config_json": strategy.config_json,
        "is_default": False,
        "is_active": True,
        "is_mine": True,
    }


@router.put("/{strategy_id}")
async def update_strategy(
    strategy_id: int,
    body: UpdateStrategyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(Strategy).where(Strategy.id == strategy_id, Strategy.user_id == user.id)
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found or not yours")

    if body.name is not None:
        if len(body.name.strip()) < 2:
            raise HTTPException(status_code=422, detail="Name must be at least 2 characters")
        strategy.name = body.name.strip()
    if body.description is not None:
        strategy.description = body.description.strip() or None
    if body.strategy_type is not None:
        if body.strategy_type not in VALID_STRATEGY_TYPES:
            raise HTTPException(status_code=422, detail=f"Invalid strategy_type: {body.strategy_type}")
        strategy.strategy_type = body.strategy_type
    if body.config_json is not None:
        _validate_config(body.config_json)
        strategy.config_json = body.config_json

    await db.commit()
    await db.refresh(strategy)
    return {
        "id": strategy.id,
        "name": strategy.name,
        "description": strategy.description,
        "strategy_type": strategy.strategy_type,
        "config_json": strategy.config_json,
        "is_default": strategy.is_default,
        "is_active": strategy.is_active,
        "is_mine": True,
    }


@router.delete("/{strategy_id}")
async def delete_strategy(
    strategy_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(Strategy).where(Strategy.id == strategy_id, Strategy.user_id == user.id)
    )
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Strategy not found")
    await db.delete(s)
    await db.commit()
    return {"status": "deleted"}


@router.post("/{strategy_id}/run")
async def run_strategy(
    strategy_id: int,
    body: RunStrategyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # Load strategy (must be user's own or a default)
    result = await db.execute(
        select(Strategy).where(
            Strategy.id == strategy_id,
            or_(Strategy.user_id == user.id, Strategy.is_default.is_(True)),
        )
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    # Resolve target symbols
    symbols: list[str] = []
    target_label = ""
    target_id = None

    if body.target_type == "holdings":
        if not user.kite_api_key or not user.kite_access_token:
            raise HTTPException(status_code=400, detail="Not connected to Kite")
        from app.services.portfolio_cache import get_holdings as cached_holdings
        try:
            holdings = await cached_holdings(user)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Kite API error: {e}")
        from app.services.portfolio_cache import active_holdings
        symbols = [h["tradingsymbol"] for h in active_holdings(holdings)]
        target_label = f"My Holdings ({len(symbols)} stocks)"

    elif body.target_type == "watchlist":
        if not body.watchlist_id:
            raise HTTPException(status_code=400, detail="watchlist_id required")
        wl_result = await db.execute(
            select(Watchlist).where(Watchlist.id == body.watchlist_id, Watchlist.user_id == user.id)
        )
        wl = wl_result.scalar_one_or_none()
        if not wl:
            raise HTTPException(status_code=404, detail="Watchlist not found")
        items_result = await db.execute(
            select(WatchlistItem).where(WatchlistItem.watchlist_id == wl.id)
        )
        symbols = [item.symbol for item in items_result.scalars().all()]
        target_label = f'Watchlist: "{wl.name}" ({len(symbols)} stocks)'
        target_id = wl.id

    elif body.target_type == "nifty50":
        symbols = NIFTY_50.copy()
        target_label = f"Nifty 50 Universe ({len(symbols)} stocks)"

    else:
        raise HTTPException(status_code=400, detail=f"Invalid target_type: {body.target_type}")

    if not symbols:
        raise HTTPException(status_code=400, detail="No symbols to evaluate")

    result_data = await run_strategy_on_symbols(
        strategy, symbols, db, user.id, target_label
    )

    # Save run to history
    run = StrategyRun(
        user_id=user.id,
        strategy_id=strategy.id,
        target_type=body.target_type,
        target_id=target_id,
        target_label=target_label,
        symbols_count=result_data.get("total_evaluated", 0),
        pass_count=result_data.get("passed_count", 0),
        result_json=result_data,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    result_data["run_id"] = run.id
    result_data["created_at"] = run.created_at.isoformat() if run.created_at else None

    return result_data


@router.get("/runs/history")
async def list_strategy_runs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 30,
) -> list[dict]:
    result = await db.execute(
        select(StrategyRun)
        .where(StrategyRun.user_id == user.id)
        .order_by(desc(StrategyRun.created_at))
        .limit(limit)
    )
    runs = result.scalars().all()

    strategy_ids = list({r.strategy_id for r in runs})
    strategies_result = await db.execute(select(Strategy).where(Strategy.id.in_(strategy_ids)))
    strategies_by_id = {s.id: s for s in strategies_result.scalars().all()}

    return [
        {
            "id": r.id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "strategy_id": r.strategy_id,
            "strategy_name": strategies_by_id.get(r.strategy_id).name if strategies_by_id.get(r.strategy_id) else "Deleted",
            "target_type": r.target_type,
            "target_label": r.target_label,
            "symbols_count": r.symbols_count,
            "pass_count": r.pass_count,
        }
        for r in runs
    ]


@router.get("/runs/{run_id}")
async def get_strategy_run(
    run_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(StrategyRun).where(StrategyRun.id == run_id, StrategyRun.user_id == user.id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Strategy run not found")
    data = dict(run.result_json)
    data["run_id"] = run.id
    data["created_at"] = run.created_at.isoformat() if run.created_at else None
    return data
