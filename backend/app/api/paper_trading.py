from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.fundamentals import StockFundamentals
from app.models.paper_trading import PaperAgent, PaperEvent
from app.models.user import User
from app.services.paper_trading import (
    build_snapshot,
    compute_scorecard,
    generate_recommendations,
    replay_events,
)

router = APIRouter()


# ── request schemas ───────────────────────────────────────────────


class CreateAgentRequest(BaseModel):
    name: str
    strategy_id: int | None = None
    initial_corpus_inr: float = 1_000_000
    config_json: dict | None = None


class UpdateAgentRequest(BaseModel):
    name: str | None = None
    config_json: dict | None = None
    is_active: bool | None = None


class CreateEventRequest(BaseModel):
    event_type: str  # BUY, SELL, DEPOSIT
    symbol: str | None = None
    exchange: str | None = "NSE"
    quantity: int | None = None
    notes: str | None = None
    source: str = "manual"


# ── helpers ───────────────────────────────────────────────────────


async def _get_agent(agent_id: int, user: User, db: AsyncSession) -> PaperAgent:
    result = await db.execute(
        select(PaperAgent).where(PaperAgent.id == agent_id, PaperAgent.user_id == user.id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


async def _get_live_prices(symbols: list[str], user: User) -> dict[str, float]:
    if not symbols or not user.kite_api_key:
        return {}
    try:
        from app.services.portfolio_cache import get_quote
        prices = {}
        for sym in symbols:
            try:
                quote = await get_quote(user, f"NSE:{sym}")
                if quote and "last_price" in quote:
                    prices[sym] = float(quote["last_price"])
            except Exception:
                pass
        return prices
    except Exception:
        return {}


def _agent_dict(agent: PaperAgent) -> dict:
    return {
        "id": agent.id,
        "name": agent.name,
        "strategy_id": agent.strategy_id,
        "initial_corpus_inr": float(agent.initial_corpus_inr),
        "config_json": agent.config_json or {},
        "is_active": agent.is_active,
        "created_at": agent.created_at.isoformat() if agent.created_at else None,
    }


# ── endpoints ─────────────────────────────────────────────────────


@router.get("/agents")
async def list_agents(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    result = await db.execute(
        select(PaperAgent)
        .where(PaperAgent.user_id == user.id)
        .order_by(PaperAgent.created_at)
    )
    agents = result.scalars().all()

    from app.models.strategy import Strategy
    strategy_ids = [a.strategy_id for a in agents if a.strategy_id]
    strategies_map: dict[int, str] = {}
    if strategy_ids:
        strat_result = await db.execute(select(Strategy).where(Strategy.id.in_(strategy_ids)))
        strategies_map = {s.id: s.name for s in strat_result.scalars().all()}

    all_position_symbols: set[str] = set()
    agent_states = []
    for agent in agents:
        state = await replay_events(agent.id, db)
        all_position_symbols.update(state.positions.keys())
        agent_states.append((agent, state))

    live_prices = await _get_live_prices(list(all_position_symbols), user)

    out = []
    for agent, state in agent_states:
        scorecard = compute_scorecard(state, float(agent.initial_corpus_inr), live_prices)
        info = _agent_dict(agent)
        info["strategy_name"] = strategies_map.get(agent.strategy_id, None) if agent.strategy_id else None
        info["scorecard"] = scorecard
        out.append(info)

    return out


@router.post("/agents")
async def create_agent(
    body: CreateAgentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not body.name or len(body.name.strip()) < 2:
        raise HTTPException(status_code=422, detail="Name must be at least 2 characters")
    if body.initial_corpus_inr <= 0:
        raise HTTPException(status_code=422, detail="Initial corpus must be positive")

    if body.strategy_id:
        from app.models.strategy import Strategy
        from sqlalchemy import or_
        s = (await db.execute(
            select(Strategy).where(
                Strategy.id == body.strategy_id,
                or_(Strategy.user_id == user.id, Strategy.is_default.is_(True)),
            )
        )).scalar_one_or_none()
        if not s:
            raise HTTPException(status_code=404, detail="Strategy not found")

    agent = PaperAgent(
        user_id=user.id,
        name=body.name.strip(),
        strategy_id=body.strategy_id,
        initial_corpus_inr=body.initial_corpus_inr,
        config_json=body.config_json or {},
        is_active=True,
    )
    db.add(agent)
    await db.flush()

    deposit = PaperEvent(
        agent_id=agent.id,
        event_type="DEPOSIT",
        price_inr=body.initial_corpus_inr,
        notes="Initial corpus",
        source="system",
    )
    db.add(deposit)
    await db.commit()
    await db.refresh(agent)

    return _agent_dict(agent)


@router.patch("/agents/{agent_id}")
async def update_agent(
    agent_id: int,
    body: UpdateAgentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    agent = await _get_agent(agent_id, user, db)
    if body.name is not None:
        agent.name = body.name.strip()
    if body.config_json is not None:
        agent.config_json = body.config_json
    if body.is_active is not None:
        agent.is_active = body.is_active
    await db.commit()
    await db.refresh(agent)
    return _agent_dict(agent)


@router.delete("/agents/{agent_id}")
async def delete_agent(
    agent_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    agent = await _get_agent(agent_id, user, db)
    await db.delete(agent)
    await db.commit()
    return {"status": "deleted"}


@router.get("/agents/{agent_id}/state")
async def get_agent_state(
    agent_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    agent = await _get_agent(agent_id, user, db)
    state = await replay_events(agent.id, db)

    all_symbols = list(state.positions.keys())
    live_prices = await _get_live_prices(all_symbols, user)

    scorecard = compute_scorecard(state, float(agent.initial_corpus_inr), live_prices)

    recommendations = await generate_recommendations(agent, state, live_prices, db)

    info = _agent_dict(agent)

    from app.models.strategy import Strategy
    strat_name = None
    if agent.strategy_id:
        s = (await db.execute(select(Strategy).where(Strategy.id == agent.strategy_id))).scalar_one_or_none()
        if s:
            strat_name = s.name
    info["strategy_name"] = strat_name
    info["scorecard"] = scorecard
    info["recommendations"] = recommendations

    return info


@router.get("/agents/{agent_id}/events")
async def get_agent_events(
    agent_id: int,
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await _get_agent(agent_id, user, db)
    result = await db.execute(
        select(PaperEvent)
        .where(PaperEvent.agent_id == agent_id)
        .order_by(desc(PaperEvent.created_at))
        .offset(offset)
        .limit(limit)
    )
    events = result.scalars().all()
    return [
        {
            "id": ev.id,
            "event_type": ev.event_type,
            "symbol": ev.symbol,
            "exchange": ev.exchange,
            "quantity": ev.quantity,
            "price_inr": float(ev.price_inr) if ev.price_inr else None,
            "notes": ev.notes,
            "source": ev.source,
            "snapshot_json": ev.snapshot_json,
            "created_at": ev.created_at.isoformat() if ev.created_at else None,
        }
        for ev in events
    ]


@router.post("/agents/{agent_id}/events")
async def create_event(
    agent_id: int,
    body: CreateEventRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    agent = await _get_agent(agent_id, user, db)
    state = await replay_events(agent.id, db)

    if body.event_type == "DEPOSIT":
        if not body.quantity and not body.symbol:
            raise HTTPException(status_code=422, detail="Provide amount as quantity field (in INR)")
        amount = body.quantity or 0
        if amount <= 0:
            raise HTTPException(status_code=422, detail="Deposit amount must be positive")
        ev = PaperEvent(
            agent_id=agent.id,
            event_type="DEPOSIT",
            price_inr=amount,
            notes=body.notes or "Manual deposit",
            source=body.source,
        )
        db.add(ev)
        await db.commit()
        await db.refresh(ev)
        return {"status": "deposited", "amount": amount, "event_id": ev.id}

    if body.event_type not in ("BUY", "SELL"):
        raise HTTPException(status_code=422, detail="event_type must be BUY, SELL, or DEPOSIT")

    if not body.symbol:
        raise HTTPException(status_code=422, detail="symbol is required for BUY/SELL")
    if not body.quantity or body.quantity <= 0:
        raise HTTPException(status_code=422, detail="quantity must be positive")

    symbol = body.symbol.upper()

    price = 0.0
    if user.kite_api_key and user.kite_access_token:
        try:
            from app.services.portfolio_cache import get_quote
            quote = await get_quote(user, f"NSE:{symbol}")
            if quote and "last_price" in quote:
                price = float(quote["last_price"])
        except Exception:
            pass

    if price <= 0:
        f = (await db.execute(
            select(StockFundamentals).where(StockFundamentals.symbol == symbol)
        )).scalar_one_or_none()
        if f and f.cmp:
            price = float(f.cmp)

    if price <= 0:
        raise HTTPException(status_code=400, detail="Cannot determine current price for this symbol")

    if body.event_type == "BUY":
        cost = body.quantity * price
        if cost > state.cash:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient cash. Need {cost:.2f}, have {state.cash:.2f}",
            )
        config = agent.config_json or {}
        max_positions = config.get("max_positions", 15)
        if symbol not in state.positions and len(state.positions) >= max_positions:
            raise HTTPException(
                status_code=400,
                detail=f"Max positions ({max_positions}) reached",
            )

    elif body.event_type == "SELL":
        pos = state.positions.get(symbol)
        if not pos or pos.quantity < body.quantity:
            held = pos.quantity if pos else 0
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient holdings. Have {held}, trying to sell {body.quantity}",
            )

    snapshot = await build_snapshot(symbol, db)

    ev = PaperEvent(
        agent_id=agent.id,
        event_type=body.event_type,
        symbol=symbol,
        exchange=body.exchange or "NSE",
        quantity=body.quantity,
        price_inr=price,
        notes=body.notes,
        source=body.source,
        snapshot_json=snapshot,
    )
    db.add(ev)
    await db.commit()
    await db.refresh(ev)

    return {
        "status": body.event_type.lower(),
        "symbol": symbol,
        "quantity": body.quantity,
        "price": round(price, 2),
        "total": round(body.quantity * price, 2),
        "event_id": ev.id,
    }


@router.post("/agents/{agent_id}/reset")
async def reset_agent(
    agent_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    agent = await _get_agent(agent_id, user, db)

    reset_ev = PaperEvent(
        agent_id=agent.id,
        event_type="RESET",
        notes="Portfolio reset",
        source="system",
    )
    db.add(reset_ev)

    deposit_ev = PaperEvent(
        agent_id=agent.id,
        event_type="DEPOSIT",
        price_inr=float(agent.initial_corpus_inr),
        notes="Initial corpus (after reset)",
        source="system",
    )
    db.add(deposit_ev)
    await db.commit()

    return {"status": "reset", "agent_id": agent.id}
