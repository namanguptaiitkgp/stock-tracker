from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def get_orders() -> dict:
    return {"status": "not implemented"}
