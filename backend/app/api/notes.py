from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.note import StockNote
from app.models.note_history import StockNoteHistory
from app.models.user import User

router = APIRouter()


class NoteUpsertRequest(BaseModel):
    content: str


def _serialize(n: StockNote) -> dict:
    return {
        "symbol": n.symbol,
        "content": n.content,
        "created_at": n.created_at.isoformat() if n.created_at else None,
        "updated_at": n.updated_at.isoformat() if n.updated_at else None,
    }


@router.get("/")
async def list_notes(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    result = await db.execute(
        select(StockNote)
        .where(StockNote.user_id == user.id)
        .order_by(desc(StockNote.updated_at), desc(StockNote.created_at))
    )
    return [_serialize(n) for n in result.scalars().all()]


@router.get("/{symbol}")
async def get_note(
    symbol: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    symbol = symbol.upper().strip()
    result = await db.execute(
        select(StockNote).where(
            StockNote.user_id == user.id,
            StockNote.symbol == symbol,
        )
    )
    note = result.scalar_one_or_none()
    if not note:
        return {"symbol": symbol, "content": "", "created_at": None, "updated_at": None}
    return _serialize(note)


@router.put("/{symbol}")
async def upsert_note(
    symbol: str,
    body: NoteUpsertRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    symbol = symbol.upper().strip()
    content = body.content.strip()

    result = await db.execute(
        select(StockNote).where(
            StockNote.user_id == user.id,
            StockNote.symbol == symbol,
        )
    )
    note = result.scalar_one_or_none()

    if not content:
        if note:
            await db.delete(note)
            await db.commit()
        return {"symbol": symbol, "content": "", "created_at": None, "updated_at": None, "deleted": True}

    if note:
        if note.content and note.content.strip():
            db.add(StockNoteHistory(user_id=user.id, symbol=symbol, content=note.content))
        note.content = content
    else:
        note = StockNote(user_id=user.id, symbol=symbol, content=content)
        db.add(note)

    await db.commit()
    await db.refresh(note)
    return _serialize(note)


@router.get("/{symbol}/history")
async def note_history(
    symbol: str,
    limit: int = 10,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    symbol = symbol.upper().strip()
    result = await db.execute(
        select(StockNoteHistory)
        .where(StockNoteHistory.user_id == user.id, StockNoteHistory.symbol == symbol)
        .order_by(desc(StockNoteHistory.created_at))
        .limit(limit)
    )
    return [
        {"content": h.content, "created_at": h.created_at.isoformat() if h.created_at else None}
        for h in result.scalars().all()
    ]


@router.delete("/{symbol}")
async def delete_note(
    symbol: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    symbol = symbol.upper().strip()
    result = await db.execute(
        select(StockNote).where(
            StockNote.user_id == user.id,
            StockNote.symbol == symbol,
        )
    )
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    await db.delete(note)
    await db.commit()
    return {"status": "deleted", "symbol": symbol}
