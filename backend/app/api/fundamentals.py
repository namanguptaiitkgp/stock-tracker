"""Fundamental Analysis API.

- Catalog (`GET /metrics`): drives the Settings rule editor.
- Rule sets (`GET`/`PUT /rule-sets`): CRUD on the user's default rule set.
- Verdict (`GET /{symbol}/verdict`): rule-evaluator output for one stock.
- Refresh (`POST /refresh`): kicks a `metric_engine.run_refresh`.
- Manual entry (`POST /{symbol}/manual-entry`): user-typed value override.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.fundamental_rule import FundamentalRule, FundamentalRuleSet
from app.models.metric import MetricManualOverride, MetricRun
from app.models.user import User
from app.services import fundamental_analysis as fa
from app.services import metric_catalog, metric_engine

router = APIRouter()


# ─── Catalog ────────────────────────────────────────────────────────────

@router.get("/metrics")
async def list_metrics(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    by_cat = await metric_catalog.list_by_category(db)
    return {
        "categories": {
            cat: [
                {
                    "key": m.key, "display_name": m.display_name, "category": m.category,
                    "unit": m.unit, "direction": m.direction,
                    "description_md": m.description_md, "formula": m.formula,
                    "default_source": m.default_source, "is_active": m.is_active,
                }
                for m in metrics
            ]
            for cat, metrics in by_cat.items()
        }
    }


# ─── Rule sets ──────────────────────────────────────────────────────────

class RulePayload(BaseModel):
    metric_key: str
    operator: Literal["gte", "lte", "gt", "lt", "eq", "between", "is_positive"]
    value_num: float | None = None
    value_low: float | None = None
    value_high: float | None = None
    weight: int = 1
    enabled: bool = True
    is_hard_filter: bool = False


class RuleSetUpdate(BaseModel):
    name: str | None = None
    rules: list[RulePayload] | None = None


def _serialize_rule(r: FundamentalRule) -> dict:
    return {
        "id": r.id,
        "metric_key": r.metric_key,
        "operator": r.operator,
        "value_num": float(r.value_num) if r.value_num is not None else None,
        "value_low": float(r.value_low) if r.value_low is not None else None,
        "value_high": float(r.value_high) if r.value_high is not None else None,
        "weight": int(r.weight),
        "enabled": r.enabled,
        "sort_order": r.sort_order,
        "is_hard_filter": bool(getattr(r, "is_hard_filter", False)),
    }


@router.get("/rule-sets")
async def list_rule_sets(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rs = await fa.get_or_create_default_rule_set(db, user.id)
    await db.commit()
    rules_res = await db.execute(
        select(FundamentalRule).where(FundamentalRule.rule_set_id == rs.id).order_by(FundamentalRule.sort_order)
    )
    rules = [_serialize_rule(r) for r in rules_res.scalars().all()]
    return {
        "rule_sets": [
            {"id": rs.id, "name": rs.name, "is_default": rs.is_default, "rules": rules}
        ]
    }


@router.put("/rule-sets/{rule_set_id}")
async def update_rule_set(
    rule_set_id: int,
    body: RuleSetUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    res = await db.execute(
        select(FundamentalRuleSet).where(
            FundamentalRuleSet.id == rule_set_id, FundamentalRuleSet.user_id == user.id,
        )
    )
    rs = res.scalar_one_or_none()
    if not rs:
        raise HTTPException(status_code=404, detail="Rule set not found")
    if body.name is not None:
        rs.name = body.name
    if body.rules is not None:
        # Wholesale replace — simpler than diffing IDs and matches the
        # frontend save pattern (one Save button rewrites everything).
        await db.execute(
            FundamentalRule.__table__.delete().where(FundamentalRule.rule_set_id == rs.id)
        )
        for i, rp in enumerate(body.rules):
            db.add(FundamentalRule(
                rule_set_id=rs.id,
                metric_key=rp.metric_key,
                operator=rp.operator,
                value_num=rp.value_num,
                value_low=rp.value_low,
                value_high=rp.value_high,
                weight=rp.weight,
                enabled=rp.enabled,
                is_hard_filter=rp.is_hard_filter,
                sort_order=i,
            ))
    await db.commit()
    return {"ok": True, "id": rs.id}


# ─── Presets ────────────────────────────────────────────────────────────


@router.get("/presets")
async def list_presets(user: User = Depends(get_current_user)) -> dict:
    """Built-in fundamental rule-set presets the user can load."""
    from app.services.screener_presets import PRESETS

    return {
        "presets": [
            {
                "key": k,
                "name": p["name"],
                "description": p["description"],
                "rule_count": len(p["rules"]),
                "hard_count": sum(1 for r in p["rules"] if r.get("is_hard_filter")),
                "soft_count": sum(1 for r in p["rules"] if not r.get("is_hard_filter")),
            }
            for k, p in PRESETS.items()
        ]
    }


@router.post("/rule-sets/{rule_set_id}/apply-preset")
async def apply_preset(
    rule_set_id: int,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Wholesale-replace the rules in `rule_set_id` with the named
    preset's rules. The user can then tweak from there. Defaults to
    the Indian-market screener preset.
    """
    from app.services.screener_presets import PRESETS

    preset_key = (body or {}).get("preset_key", "indian_screener")
    preset = PRESETS.get(preset_key)
    if not preset:
        raise HTTPException(404, f"Unknown preset: {preset_key}")

    res = await db.execute(
        select(FundamentalRuleSet).where(
            FundamentalRuleSet.id == rule_set_id, FundamentalRuleSet.user_id == user.id,
        )
    )
    rs = res.scalar_one_or_none()
    if not rs:
        raise HTTPException(404, "Rule set not found")

    await db.execute(
        FundamentalRule.__table__.delete().where(FundamentalRule.rule_set_id == rs.id)
    )
    for i, r in enumerate(preset["rules"]):
        db.add(FundamentalRule(
            rule_set_id=rs.id,
            metric_key=r["metric_key"],
            operator=r["operator"],
            value_num=r.get("value_num"),
            value_low=r.get("value_low"),
            value_high=r.get("value_high"),
            weight=r.get("weight", 1),
            enabled=True,
            is_hard_filter=r.get("is_hard_filter", False),
            sort_order=r.get("sort_order", i),
        ))
    rs.name = preset["name"]
    await db.commit()
    return {
        "ok": True,
        "rule_set_id": rs.id,
        "preset_key": preset_key,
        "rules_loaded": len(preset["rules"]),
    }


# ─── Verdict ────────────────────────────────────────────────────────────

@router.get("/{symbol}/verdict")
async def get_verdict(
    symbol: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    verdict = await fa.evaluate_for_user(db, user.id, symbol.upper())
    return verdict.to_dict()


# ─── Refresh ────────────────────────────────────────────────────────────

class RefreshRequest(BaseModel):
    scope: Literal["stock", "watchlist", "portfolio"]
    symbol: str | None = None
    watchlist_id: int | None = None


@router.post("/refresh")
async def refresh(
    body: RefreshRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    run = await metric_engine.run_refresh(
        db, user,
        scope=body.scope,
        target_symbol=body.symbol,
        target_id=body.watchlist_id,
    )
    return {
        "run_id": run.id,
        "scope": run.scope,
        "stocks_total": run.stocks_total,
        "stocks_ok": run.stocks_ok,
        "stocks_failed": run.stocks_failed,
        "status": run.status,
    }


@router.get("/runs/{run_id}")
async def get_run(
    run_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    res = await db.execute(
        select(MetricRun).where(MetricRun.id == run_id, MetricRun.user_id == user.id)
    )
    run = res.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "id": run.id,
        "scope": run.scope,
        "target_id": run.target_id,
        "target_symbol": run.target_symbol,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "status": run.status,
        "stocks_total": run.stocks_total,
        "stocks_ok": run.stocks_ok,
        "stocks_failed": run.stocks_failed,
        "error_summary": run.error_summary,
    }


# ─── Manual entry ───────────────────────────────────────────────────────

class ManualEntryRequest(BaseModel):
    metric_key: str
    value_num: float | None = None
    value_str: str | None = None
    note: str | None = None


@router.post("/{symbol}/manual-entry")
async def manual_entry(
    symbol: str,
    body: ManualEntryRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if body.value_num is None and not body.value_str:
        raise HTTPException(status_code=400, detail="Provide value_num or value_str")
    from datetime import datetime, timezone
    sym_u = symbol.upper()
    # Upsert
    res = await db.execute(
        select(MetricManualOverride).where(
            MetricManualOverride.user_id == user.id,
            MetricManualOverride.symbol == sym_u,
            MetricManualOverride.metric_key == body.metric_key,
        )
    )
    row = res.scalar_one_or_none()
    if row:
        row.value_num = body.value_num
        row.value_str = body.value_str
        row.note = body.note
        row.set_at = datetime.now(timezone.utc)
    else:
        db.add(MetricManualOverride(
            user_id=user.id, symbol=sym_u, exchange="NSE",
            metric_key=body.metric_key,
            value_num=body.value_num, value_str=body.value_str,
            note=body.note, set_at=datetime.now(timezone.utc),
        ))
    await db.commit()
    return {"ok": True, "symbol": sym_u, "metric_key": body.metric_key}
