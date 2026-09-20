from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fundamentals import StockFundamentals
from app.models.paper_trading import PaperAgent, PaperEvent


# ── lot / position helpers ────────────────────────────────────────


@dataclass
class Lot:
    quantity: int
    price: float
    bought_at: datetime


@dataclass
class Position:
    lots: list[Lot] = field(default_factory=list)

    @property
    def quantity(self) -> int:
        return sum(lot.quantity for lot in self.lots)

    @property
    def avg_cost(self) -> float:
        total_qty = self.quantity
        if total_qty == 0:
            return 0.0
        return sum(lot.quantity * lot.price for lot in self.lots) / total_qty

    @property
    def total_cost(self) -> float:
        return sum(lot.quantity * lot.price for lot in self.lots)


@dataclass
class ClosedTrade:
    symbol: str
    quantity: int
    buy_price: float
    sell_price: float
    pnl: float
    pnl_pct: float
    bought_at: datetime
    sold_at: datetime
    holding_days: int


@dataclass
class PortfolioState:
    cash: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)
    closed_trades: list[ClosedTrade] = field(default_factory=list)
    realized_pnl: float = 0.0


# ── event replay ──────────────────────────────────────────────────


async def replay_events(agent_id: int, db: AsyncSession) -> PortfolioState:
    reset_q = await db.execute(
        select(PaperEvent)
        .where(PaperEvent.agent_id == agent_id, PaperEvent.event_type == "RESET")
        .order_by(desc(PaperEvent.created_at))
        .limit(1)
    )
    reset_event = reset_q.scalar_one_or_none()

    q = select(PaperEvent).where(PaperEvent.agent_id == agent_id)
    if reset_event:
        q = q.where(PaperEvent.created_at >= reset_event.created_at)
    q = q.order_by(PaperEvent.created_at)

    result = await db.execute(q)
    events = result.scalars().all()

    state = PortfolioState()

    for ev in events:
        if ev.event_type == "RESET":
            state = PortfolioState()
        elif ev.event_type == "DEPOSIT":
            state.cash += float(ev.price_inr or 0)
        elif ev.event_type == "BUY":
            cost = ev.quantity * float(ev.price_inr)
            state.cash -= cost
            pos = state.positions.setdefault(ev.symbol, Position())
            pos.lots.append(Lot(
                quantity=ev.quantity,
                price=float(ev.price_inr),
                bought_at=ev.created_at,
            ))
        elif ev.event_type == "SELL":
            sell_price = float(ev.price_inr)
            sell_qty = ev.quantity
            state.cash += sell_qty * sell_price

            pos = state.positions.get(ev.symbol)
            if pos:
                remaining = sell_qty
                while remaining > 0 and pos.lots:
                    lot = pos.lots[0]
                    take = min(remaining, lot.quantity)
                    pnl = (sell_price - lot.price) * take
                    pnl_pct = ((sell_price / lot.price) - 1) * 100 if lot.price > 0 else 0
                    holding_days = (ev.created_at - lot.bought_at).days

                    state.closed_trades.append(ClosedTrade(
                        symbol=ev.symbol,
                        quantity=take,
                        buy_price=lot.price,
                        sell_price=sell_price,
                        pnl=pnl,
                        pnl_pct=pnl_pct,
                        bought_at=lot.bought_at,
                        sold_at=ev.created_at,
                        holding_days=holding_days,
                    ))
                    state.realized_pnl += pnl
                    lot.quantity -= take
                    remaining -= take
                    if lot.quantity == 0:
                        pos.lots.pop(0)

                if pos.quantity == 0:
                    del state.positions[ev.symbol]

    return state


# ── scorecard ─────────────────────────────────────────────────────


def compute_scorecard(
    state: PortfolioState,
    initial_corpus: float,
    live_prices: dict[str, float],
) -> dict:
    positions_value = 0.0
    unrealized_pnl = 0.0
    position_details = []

    for symbol, pos in state.positions.items():
        current_price = live_prices.get(symbol, pos.avg_cost)
        pos_value = pos.quantity * current_price
        pos_unrealized = (current_price - pos.avg_cost) * pos.quantity
        positions_value += pos_value
        unrealized_pnl += pos_unrealized
        position_details.append({
            "symbol": symbol,
            "quantity": pos.quantity,
            "avg_cost": round(pos.avg_cost, 2),
            "current_price": round(current_price, 2),
            "value": round(pos_value, 2),
            "unrealized_pnl": round(pos_unrealized, 2),
            "unrealized_pnl_pct": round(((current_price / pos.avg_cost) - 1) * 100, 2) if pos.avg_cost > 0 else 0,
        })

    portfolio_value = state.cash + positions_value
    total_return_pct = ((portfolio_value / initial_corpus) - 1) * 100 if initial_corpus > 0 else 0

    winning = [t for t in state.closed_trades if t.pnl > 0]
    total_closed = len(state.closed_trades)
    win_rate = (len(winning) / total_closed * 100) if total_closed > 0 else 0

    avg_holding = 0
    if state.closed_trades:
        avg_holding = sum(t.holding_days for t in state.closed_trades) / len(state.closed_trades)

    best_trade = None
    worst_trade = None
    if state.closed_trades:
        best = max(state.closed_trades, key=lambda t: t.pnl)
        worst = min(state.closed_trades, key=lambda t: t.pnl)
        best_trade = {"symbol": best.symbol, "pnl": round(best.pnl, 2), "pnl_pct": round(best.pnl_pct, 2)}
        worst_trade = {"symbol": worst.symbol, "pnl": round(worst.pnl, 2), "pnl_pct": round(worst.pnl_pct, 2)}

    return {
        "portfolio_value": round(portfolio_value, 2),
        "cash": round(state.cash, 2),
        "positions_value": round(positions_value, 2),
        "total_return_pct": round(total_return_pct, 2),
        "realized_pnl": round(state.realized_pnl, 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "win_rate": round(win_rate, 1),
        "avg_holding_days": round(avg_holding, 1),
        "total_trades": total_closed,
        "positions_count": len(state.positions),
        "best_trade": best_trade,
        "worst_trade": worst_trade,
        "positions": sorted(position_details, key=lambda p: abs(p["unrealized_pnl"]), reverse=True),
    }


# ── snapshot builder ──────────────────────────────────────────────


async def build_snapshot(symbol: str, db: AsyncSession) -> dict | None:
    f = (await db.execute(
        select(StockFundamentals).where(StockFundamentals.symbol == symbol.upper())
    )).scalar_one_or_none()
    if not f:
        return None

    snap: dict = {
        "fundamentals": {
            "cmp": float(f.cmp) if f.cmp else None,
            "pe": float(f.pe_ratio) if f.pe_ratio else None,
            "pb": float(f.pb_ratio) if f.pb_ratio else None,
            "market_cap_cr": round(float(f.market_cap) / 1e7, 1) if f.market_cap else None,
            "roe": round(float(f.roe) * 100, 2) if f.roe else None,
            "debt_equity": float(f.debt_to_equity) if f.debt_to_equity else None,
            "revenue_growth_pct": round(float(f.revenue_growth_1y) * 100, 1) if f.revenue_growth_1y else None,
            "eps_growth_pct": round(float(f.eps_growth_1y) * 100, 1) if f.eps_growth_1y else None,
            "dividend_yield": round(float(f.dividend_yield) * 100, 2) if f.dividend_yield else None,
        },
    }

    from app.models.investment_decision import InvestmentDecision
    dec = (await db.execute(
        select(InvestmentDecision)
        .where(InvestmentDecision.symbol == symbol.upper())
        .order_by(desc(InvestmentDecision.created_at))
        .limit(1)
    )).scalar_one_or_none()
    if dec and dec.result_json:
        r = dec.result_json
        snap["ai_verdict"] = {
            "verdict": r.get("verdict"),
            "confidence": r.get("confidence"),
            "target_price": r.get("target_price"),
            "stop_loss": r.get("stop_loss"),
            "time_horizon": r.get("time_horizon"),
        }

    return snap


# ── recommendations engine ────────────────────────────────────────


async def generate_recommendations(
    agent: PaperAgent,
    state: PortfolioState,
    live_prices: dict[str, float],
    db: AsyncSession,
) -> list[dict]:
    if not agent.strategy_id:
        return []

    from app.models.strategy import Strategy
    from app.models.investment_decision import InvestmentDecision

    strategy = (await db.execute(
        select(Strategy).where(Strategy.id == agent.strategy_id)
    )).scalar_one_or_none()
    if not strategy:
        return []

    config = agent.config_json or {}
    min_confidence = config.get("min_confidence", 60)
    max_positions = config.get("max_positions", 15)
    max_position_pct = config.get("max_position_pct", 15)
    fno_only = config.get("fno_only", False)

    current_positions = len(state.positions)
    if current_positions >= max_positions:
        return []

    portfolio_value = state.cash + sum(
        pos.quantity * live_prices.get(sym, pos.avg_cost)
        for sym, pos in state.positions.items()
    )

    from app.services.strategy_runner import _check_filters
    from app.services.fundamentals_service import get_fundamentals_bulk

    invest_q = await db.execute(
        select(InvestmentDecision)
        .where(InvestmentDecision.user_id == agent.user_id)
        .order_by(desc(InvestmentDecision.created_at))
    )
    decisions = invest_q.scalars().all()

    seen: set[str] = set()
    invest_symbols: list[tuple[str, dict]] = []
    for dec in decisions:
        sym = dec.symbol.upper()
        if sym in seen:
            continue
        seen.add(sym)
        r = dec.result_json or {}
        verdict = r.get("verdict", "")
        confidence = r.get("confidence", 0)
        if verdict == "INVEST" and confidence >= min_confidence and sym not in state.positions:
            invest_symbols.append((sym, r))

    if not invest_symbols:
        return []

    symbols_to_check = [s for s, _ in invest_symbols]
    fundamentals_map = await get_fundamentals_bulk(symbols_to_check, db, user_id=agent.user_id)

    if fno_only:
        from app.services.market.fno_universe import get_fno_sets
        nse_fno, bse_fno = await get_fno_sets()
        fno_set = nse_fno | bse_fno
    else:
        fno_set = None

    filters = strategy.config_json.get("filters", {})
    recommendations: list[dict] = []
    slots_remaining = max_positions - current_positions

    for sym, verdict_data in invest_symbols:
        if slots_remaining <= 0:
            break
        if fno_set is not None and sym not in fno_set:
            continue

        f = fundamentals_map.get(sym)
        if not f:
            continue

        passed, _ = _check_filters(f, filters)
        if not passed:
            continue

        confidence = verdict_data.get("confidence", 0)
        price = live_prices.get(sym, float(f.cmp) if f.cmp else 0)
        if price <= 0:
            continue

        max_amount = (max_position_pct / 100) * portfolio_value
        amount = (confidence / 100) * max_amount
        quantity = int(amount / price)
        if quantity <= 0 or quantity * price > state.cash:
            continue

        from app.services.market.fno_universe import get_fno_sets as _get_fno
        if fno_set is None:
            nse_fno, bse_fno = await _get_fno()
            has_fno = sym in (nse_fno | bse_fno)
        else:
            has_fno = sym in fno_set

        recommendations.append({
            "symbol": sym,
            "exchange": "NSE",
            "side": "BUY",
            "suggested_quantity": quantity,
            "current_price": round(price, 2),
            "estimated_cost": round(quantity * price, 2),
            "reasoning": f"INVEST at {confidence}% confidence. Target {verdict_data.get('target_price', '?')}.",
            "ai_verdict": {
                "verdict": verdict_data.get("verdict"),
                "confidence": confidence,
                "target_price": verdict_data.get("target_price"),
            },
            "has_fno": has_fno,
        })
        slots_remaining -= 1

    sell_recs = []
    for sym in list(state.positions.keys()):
        latest = None
        for dec in decisions:
            if dec.symbol.upper() == sym:
                latest = dec
                break
        if latest and latest.result_json:
            v = latest.result_json.get("verdict", "")
            if v == "AVOID":
                pos = state.positions[sym]
                price = live_prices.get(sym, pos.avg_cost)
                sell_recs.append({
                    "symbol": sym,
                    "exchange": "NSE",
                    "side": "SELL",
                    "suggested_quantity": pos.quantity,
                    "current_price": round(price, 2),
                    "estimated_cost": round(pos.quantity * price, 2),
                    "reasoning": f"AI verdict flipped to AVOID. Current P&L: {((price / pos.avg_cost) - 1) * 100:.1f}%.",
                    "ai_verdict": {"verdict": "AVOID", "confidence": latest.result_json.get("confidence", 0)},
                    "has_fno": False,
                })

    return sell_recs + recommendations
