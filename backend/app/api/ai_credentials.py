from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.credential_rotation import is_exhausted
from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.ai_credential import AiCredential
from app.models.user import User
from app.schemas.ai_credential import (
    AiCredentialCreate,
    AiCredentialResponse,
    AiCredentialStatusResponse,
    AiCredentialUpdate,
)

router = APIRouter()


def _mask_key(key: str | None) -> str | None:
    if not key or len(key) < 12:
        return "••• configured" if key else None
    return key[:8] + "****" + key[-4:]


def _to_response(cred: AiCredential) -> AiCredentialResponse:
    return AiCredentialResponse(
        id=cred.id,
        credential_type=cred.credential_type,
        label=cred.label,
        priority=cred.priority,
        is_active=cred.is_active,
        default_model=cred.default_model,
        api_key_masked=_mask_key(cred.encrypted_api_key) if cred.credential_type == "gemini_api_key" else None,
        project_id=cred.project_id,
        location=cred.location,
        client_email=cred.client_email,
        private_key_id=cred.private_key_id,
        private_key_configured=bool(cred.encrypted_private_key),
        token_uri=cred.token_uri,
        is_exhausted_today=is_exhausted(cred.id),
        created_at=cred.created_at,
        updated_at=cred.updated_at,
    )


@router.get("/")
async def list_credentials(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AiCredentialResponse]:
    result = await db.execute(
        select(AiCredential)
        .where(AiCredential.user_id == user.id)
        .order_by(AiCredential.priority.asc(), AiCredential.id.asc())
    )
    return [_to_response(c) for c in result.scalars().all()]


@router.post("/")
async def create_credential(
    body: AiCredentialCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AiCredentialResponse:
    if body.credential_type == "gemini_api_key" and not body.api_key:
        raise HTTPException(status_code=400, detail="API key is required for gemini_api_key type")
    if body.credential_type == "vertex_service_account":
        for field in ("project_id", "location", "client_email", "private_key"):
            if not getattr(body, field):
                raise HTTPException(status_code=400, detail=f"{field} is required for vertex_service_account type")

    cred = AiCredential(
        user_id=user.id,
        credential_type=body.credential_type,
        label=body.label,
        priority=body.priority,
        is_active=body.is_active,
        default_model=body.default_model,
        encrypted_api_key=body.api_key if body.credential_type == "gemini_api_key" else None,
        project_id=body.project_id if body.credential_type == "vertex_service_account" else None,
        location=body.location if body.credential_type == "vertex_service_account" else None,
        client_email=body.client_email if body.credential_type == "vertex_service_account" else None,
        private_key_id=body.private_key_id if body.credential_type == "vertex_service_account" else None,
        encrypted_private_key=body.private_key if body.credential_type == "vertex_service_account" else None,
        token_uri=body.token_uri if body.credential_type == "vertex_service_account" else None,
    )
    db.add(cred)
    await db.commit()
    await db.refresh(cred)
    return _to_response(cred)


@router.put("/{credential_id}")
async def update_credential(
    credential_id: int,
    body: AiCredentialUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AiCredentialResponse:
    result = await db.execute(
        select(AiCredential).where(AiCredential.id == credential_id, AiCredential.user_id == user.id)
    )
    cred = result.scalar_one_or_none()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")

    if body.label is not None:
        cred.label = body.label
    if body.priority is not None:
        cred.priority = body.priority
    if body.is_active is not None:
        cred.is_active = body.is_active
    if body.default_model is not None:
        cred.default_model = body.default_model
    if body.api_key is not None:
        cred.encrypted_api_key = body.api_key
    if body.project_id is not None:
        cred.project_id = body.project_id
    if body.location is not None:
        cred.location = body.location
    if body.client_email is not None:
        cred.client_email = body.client_email
    if body.private_key_id is not None:
        cred.private_key_id = body.private_key_id
    if body.private_key is not None:
        cred.encrypted_private_key = body.private_key
    if body.token_uri is not None:
        cred.token_uri = body.token_uri

    await db.commit()
    await db.refresh(cred)
    return _to_response(cred)


@router.delete("/{credential_id}")
async def delete_credential(
    credential_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(AiCredential).where(AiCredential.id == credential_id, AiCredential.user_id == user.id)
    )
    cred = result.scalar_one_or_none()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")

    await db.delete(cred)
    await db.commit()
    return {"status": "deleted", "id": credential_id}


@router.get("/status")
async def credentials_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AiCredentialStatusResponse]:
    result = await db.execute(
        select(AiCredential)
        .where(AiCredential.user_id == user.id)
        .order_by(AiCredential.priority.asc())
    )
    return [
        AiCredentialStatusResponse(
            id=c.id,
            label=c.label,
            credential_type=c.credential_type,
            is_active=c.is_active,
            is_exhausted_today=is_exhausted(c.id),
        )
        for c in result.scalars().all()
    ]
