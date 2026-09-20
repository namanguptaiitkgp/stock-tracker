import base64

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import attributes

from app.ai.gemini_client import list_available_models
from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.user import User

router = APIRouter()


def mask_key(key: str | None) -> str | None:
    if not key or len(key) < 8:
        return None
    return key[:4] + "*" * (len(key) - 8) + key[-4:]


class ApiKeysResponse(BaseModel):
    kite_api_key: str | None = None
    kite_api_secret: str | None = None
    kite_connected: bool = False
    gemini_api_key: str | None = None
    gemini_vertex_ai: bool = False
    anthropic_api_key: str | None = None
    ai_credentials_count: int = 0


class UpdateKiteKeysRequest(BaseModel):
    kite_api_key: str
    kite_api_secret: str


class UpdateGeminiKeyRequest(BaseModel):
    gemini_api_key: str


class UpdateAnthropicKeyRequest(BaseModel):
    anthropic_api_key: str


class RiskSettingsRequest(BaseModel):
    risk_max_position_size_pct: float | None = None
    risk_max_total_exposure_pct: float | None = None
    risk_max_daily_loss_inr: float | None = None
    risk_max_drawdown_pct: float | None = None
    risk_max_orders_per_day: int | None = None
    risk_max_order_value_inr: float | None = None
    risk_kill_switch: bool | None = None
    opus_max_daily_budget_usd: float | None = None
    gemini_model: str | None = None
    opus_model: str | None = None


class AppearanceRequest(BaseModel):
    wallpaper_enabled: bool | None = None
    wallpaper_preset: str | None = None
    wallpaper_url: str | None = None
    wallpaper_opacity: float | None = None
    theme: str | None = None


@router.get("/api-keys")
async def get_api_keys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiKeysResponse:
    from app.ai.credential_rotation import get_active_credentials

    creds = await get_active_credentials(user.id, db)

    return ApiKeysResponse(
        kite_api_key=mask_key(user.kite_api_key),
        kite_api_secret=mask_key(user.kite_api_secret),
        kite_connected=bool(user.kite_access_token),
        gemini_api_key=mask_key(user.gemini_api_key),
        gemini_vertex_ai=any(c.credential_type == "vertex_service_account" for c in creds),
        anthropic_api_key=mask_key(user.anthropic_api_key),
        ai_credentials_count=len(creds),
    )


@router.get("/gemini-models")
async def get_gemini_models(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    try:
        models = await list_available_models(user_id=user.id, db=db)
        return models
    except Exception as e:
        return [{"id": "error", "name": f"Failed to fetch models: {e}", "description": ""}]


@router.put("/kite")
async def update_kite_keys(
    body: UpdateKiteKeysRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    user.kite_api_key = body.kite_api_key
    user.kite_api_secret = body.kite_api_secret
    user.kite_access_token = None
    await db.commit()
    return {"status": "updated", "kite_api_key": mask_key(body.kite_api_key)}


@router.put("/gemini")
async def update_gemini_key(
    body: UpdateGeminiKeyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    user.gemini_api_key = body.gemini_api_key
    await db.commit()
    return {"status": "updated", "gemini_api_key": mask_key(body.gemini_api_key)}


@router.put("/anthropic")
async def update_anthropic_key(
    body: UpdateAnthropicKeyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    user.anthropic_api_key = body.anthropic_api_key
    await db.commit()
    return {"status": "updated", "anthropic_api_key": mask_key(body.anthropic_api_key)}


@router.get("/risk")
async def get_risk_settings(user: User = Depends(get_current_user)) -> dict:
    defaults = {
        "risk_max_position_size_pct": 10,
        "risk_max_total_exposure_pct": 80,
        "risk_max_daily_loss_inr": 5000,
        "risk_max_drawdown_pct": 5,
        "risk_max_orders_per_day": 20,
        "risk_max_order_value_inr": 100000,
        "risk_kill_switch": False,
        "opus_max_daily_budget_usd": 1.0,
        "gemini_model": "gemini-2.5-flash-lite",
        "opus_model": "claude-opus-4-6",
    }
    settings = user.settings_json or {}
    return {**defaults, **settings}


@router.put("/risk")
async def update_risk_settings(
    body: RiskSettingsRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    current = user.settings_json or {}
    updates = body.model_dump(exclude_none=True)
    current.update(updates)
    user.settings_json = dict(current)
    attributes.flag_modified(user, "settings_json")
    await db.commit()
    return {"status": "updated", "settings": current}


@router.get("/appearance")
async def get_appearance(user: User = Depends(get_current_user)) -> dict:
    settings = user.settings_json or {}
    return {
        "wallpaper_enabled": settings.get("wallpaper_enabled", True),
        "wallpaper_preset": settings.get("wallpaper_preset", "none"),
        "wallpaper_url": settings.get("wallpaper_url"),
        "wallpaper_upload": settings.get("wallpaper_upload"),  # persisted upload
        "wallpaper_opacity": settings.get("wallpaper_opacity", 0.4),
        "theme": settings.get("theme", "dark"),
    }


@router.put("/appearance")
async def update_appearance(
    body: AppearanceRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    current = dict(user.settings_json or {})
    updates = body.model_dump(exclude_none=True)
    current.update(updates)
    user.settings_json = current
    attributes.flag_modified(user, "settings_json")
    await db.commit()
    return {"status": "updated", "appearance": {k: current.get(k) for k in ("wallpaper_enabled", "wallpaper_preset", "wallpaper_url", "wallpaper_opacity")}}


ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}
MAX_WALLPAPER_SIZE = 8 * 1024 * 1024  # 8 MB


@router.post("/wallpaper-upload")
async def upload_wallpaper(
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    content_type = file.content_type or ""
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image type: {content_type}. Use PNG, JPEG, WebP, or GIF.",
        )

    data = await file.read()
    if len(data) > MAX_WALLPAPER_SIZE:
        raise HTTPException(status_code=400, detail="Image too large (max 8 MB)")

    b64 = base64.b64encode(data).decode("utf-8")
    data_url = f"data:{content_type};base64,{b64}"

    current = dict(user.settings_json or {})
    current["wallpaper_upload"] = data_url  # permanent store — survives preset switches
    current["wallpaper_url"] = data_url     # active wallpaper
    current["wallpaper_preset"] = "none"
    user.settings_json = current
    attributes.flag_modified(user, "settings_json")
    await db.commit()

    return {
        "status": "uploaded",
        "size_bytes": len(data),
        "content_type": content_type,
    }
