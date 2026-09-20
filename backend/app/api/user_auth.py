from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_db
from app.dependencies import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.models.user import User

router = APIRouter()


from app.observability.ratelimit import auth_limit as _auth_limit


class RegisterRequest(BaseModel):
    username: str
    email: str | None = None
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class SetupStatusResponse(BaseModel):
    is_setup: bool
    user_count: int


class UpdateProfileRequest(BaseModel):
    username: str | None = None
    email: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.get("/setup-status")
async def setup_status(db: AsyncSession = Depends(get_db)) -> SetupStatusResponse:
    result = await db.execute(select(func.count(User.id)))
    count = result.scalar_one()
    return SetupStatusResponse(is_setup=count > 0, user_count=count)


@router.post("/register")
@_auth_limit()
async def register(request: Request, body: RegisterRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    result = await db.execute(select(func.count(User.id)))
    count = result.scalar_one()
    if count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin user already exists. Only one user is allowed.",
        )

    if len(body.password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 6 characters",
        )

    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        settings_json={
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
        },
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id)
    return TokenResponse(
        access_token=token,
        user={"id": user.id, "username": user.username, "email": user.email},
    )


@router.post("/login")
@_auth_limit()
async def login(request: Request, body: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    token = create_access_token(user.id)
    return TokenResponse(
        access_token=token,
        user={"id": user.id, "username": user.username, "email": user.email},
    )


@router.patch("/profile")
@_auth_limit()
async def update_profile(
    request: Request,
    body: UpdateProfileRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Update the current user's username and/or email."""
    if body.username is not None:
        new_username = body.username.strip()
        if len(new_username) < 3:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username must be at least 3 characters",
            )
        if new_username != user.username:
            # Enforce uniqueness (case-sensitive, matches login lookup).
            existing = await db.execute(
                select(func.count(User.id)).where(
                    User.username == new_username, User.id != user.id
                )
            )
            if existing.scalar_one() > 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="That username is already taken",
                )
            user.username = new_username

    if body.email is not None:
        user.email = body.email.strip() or None

    await db.commit()
    await db.refresh(user)
    return {"id": user.id, "username": user.username, "email": user.email}


@router.post("/change-password")
@_auth_limit()
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Change the current user's password after verifying the current one."""
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )
    if len(body.new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 6 characters",
        )
    if verify_password(body.new_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from the current one",
        )

    user.password_hash = hash_password(body.new_password)
    await db.commit()
    return {"status": "ok"}


@router.get("/me")
async def me(user: User = Depends(get_current_user)) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "has_kite_key": bool(user.kite_api_key),
        "has_gemini_key": bool(user.gemini_api_key),
        "has_anthropic_key": bool(user.anthropic_api_key),
        "settings": user.settings_json or {},
    }
