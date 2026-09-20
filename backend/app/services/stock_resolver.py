import io

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gemini_client import extract_stocks_from_image, resolve_stock_symbols
from app.models.stock import Stock


async def parse_upload(
    file_bytes: bytes,
    content_type: str,
    filename: str,
    user_id: int,
    db,
) -> list[str]:
    if content_type in ("image/png", "image/jpeg", "image/jpg", "image/webp"):
        return await extract_stocks_from_image(user_id, db, file_bytes, content_type)

    if filename.endswith(".csv") or content_type == "text/csv":
        return _parse_csv(file_bytes)

    if filename.endswith((".xlsx", ".xls")) or "spreadsheet" in content_type:
        return _parse_excel(file_bytes)

    return _parse_text(file_bytes)


def _parse_csv(data: bytes) -> list[str]:
    try:
        df = pd.read_csv(io.BytesIO(data))
        return _extract_from_dataframe(df)
    except Exception:
        return _parse_text(data)


def _parse_excel(data: bytes) -> list[str]:
    try:
        df = pd.read_excel(io.BytesIO(data), engine="openpyxl")
        return _extract_from_dataframe(df)
    except Exception:
        return []


def _parse_text(data: bytes) -> list[str]:
    text = data.decode("utf-8", errors="ignore")
    items = []
    for line in text.strip().splitlines():
        for part in line.split(","):
            cleaned = part.strip().strip('"').strip("'").strip()
            if cleaned and len(cleaned) < 100:
                items.append(cleaned)
    return [i for i in items if i]


def _extract_from_dataframe(df: pd.DataFrame) -> list[str]:
    symbol_cols = [
        c for c in df.columns
        if any(k in c.lower() for k in ("symbol", "ticker", "stock", "scrip", "name", "company"))
    ]

    target_cols = symbol_cols if symbol_cols else [c for c in df.columns if df[c].dtype == object][:1]

    stocks = []
    for col in target_cols:
        for val in df[col].dropna().astype(str):
            cleaned = val.strip()
            if cleaned and cleaned.lower() not in ("nan", "none", "") and len(cleaned) < 50:
                stocks.append(cleaned)

    return list(dict.fromkeys(stocks))


async def resolve_and_match(
    raw_names: list[str],
    user_id: int,
    db: AsyncSession,
) -> tuple[list[dict], list[dict]]:
    raw_names = list(dict.fromkeys(n.strip() for n in raw_names if n.strip()))
    if not raw_names:
        return [], []

    matched: list[dict] = []
    errors: list[dict] = []
    needs_ai: list[str] = []

    # Phase 1: direct DB match
    for name in raw_names:
        result = await db.execute(
            select(Stock).where(
                (Stock.tradingsymbol == name.upper()) |
                (Stock.tradingsymbol == name.upper().replace(" ", ""))
            )
        )
        stock = result.scalar_one_or_none()
        if stock:
            matched.append({
                "input": name,
                "symbol": stock.tradingsymbol,
                "name": stock.name or stock.tradingsymbol,
                "exchange": stock.exchange,
                "stock_id": stock.id,
                "confidence": "exact",
            })
        else:
            needs_ai.append(name)

    # Phase 2: AI resolution for unmatched via credential rotation
    if needs_ai:
        from app.ai.credential_rotation import NoCredentialsConfiguredError, AllCredentialsExhaustedError
        try:
            resolved = await resolve_stock_symbols(user_id, db, needs_ai)

            for name in needs_ai:
                info = resolved.get(name, {})
                symbol = info.get("symbol")
                confidence = info.get("confidence", "low")

                if not symbol or confidence == "low":
                    errors.append({
                        "input": name,
                        "symbol": info.get("symbol"),
                        "error": info.get("error") or f"Could not map '{name}' to any NSE stock",
                    })
                    continue

                # Try to find AI-resolved symbol in DB
                result = await db.execute(
                    select(Stock).where(Stock.tradingsymbol == symbol)
                )
                stock = result.scalar_one_or_none()

                matched.append({
                    "input": name,
                    "symbol": symbol,
                    "name": (stock.name if stock else info.get("name")) or symbol,
                    "exchange": stock.exchange if stock else "NSE",
                    "stock_id": stock.id if stock else None,
                    "confidence": confidence,
                })

        except (NoCredentialsConfiguredError, AllCredentialsExhaustedError):
            # No AI credentials available — report all unmatched as errors
            for name in needs_ai:
                errors.append({
                    "input": name,
                    "symbol": None,
                    "error": f"Could not map '{name}' — no AI credentials configured",
                })

    return matched, errors
