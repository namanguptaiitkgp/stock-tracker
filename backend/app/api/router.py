from fastapi import APIRouter

from app.api.ai_credentials import router as ai_credentials_router
from app.api.analysis import router as analysis_router
from app.api.auth import router as auth_router
from app.api.finance import router as finance_router
from app.api.fno import router as fno_router
from app.api.health import router as health_router
from app.api.fundamentals import router as fundamentals_router
from app.api.holdings_metadata import router as holdings_metadata_router
from app.api.system import router as system_router
from app.api.indices import router as indices_router
from app.api.today import router as today_router
from app.api.investment import router as investment_router
from app.api.market_data import router as market_data_router
from app.api.news_inbox import router as news_inbox_router
from app.api.review_alerts import router as review_alerts_router
from app.api.orders import router as orders_router
from app.api.portfolio import router as portfolio_router
from app.api.notes import router as notes_router
from app.api.settings_api import router as settings_router
from app.api.smart_money import router as smart_money_router
from app.api.stock_search import router as stock_search_router
from app.api.strategies import router as strategies_router
from app.api.paper_trading import router as paper_trading_router
from app.api.user_auth import router as user_auth_router
from app.api.watchlist import router as watchlist_router

router = APIRouter()

router.include_router(user_auth_router, prefix="/user", tags=["user-auth"])
router.include_router(auth_router, prefix="/auth", tags=["kite-auth"])
router.include_router(settings_router, prefix="/settings", tags=["settings"])
router.include_router(ai_credentials_router, prefix="/settings/ai-credentials", tags=["ai-credentials"])
router.include_router(watchlist_router, prefix="/watchlists", tags=["watchlists"])
router.include_router(analysis_router, prefix="/analysis", tags=["analysis"])
router.include_router(market_data_router, prefix="/market-data", tags=["market-data"])
router.include_router(portfolio_router, prefix="/portfolio", tags=["portfolio"])
router.include_router(orders_router, prefix="/orders", tags=["orders"])
router.include_router(strategies_router, prefix="/strategies", tags=["strategies"])
router.include_router(notes_router, prefix="/notes", tags=["notes"])
router.include_router(investment_router, prefix="/investment", tags=["investment"])
router.include_router(stock_search_router, prefix="/stocks", tags=["stocks"])
router.include_router(today_router, prefix="/today", tags=["today"])
router.include_router(smart_money_router, prefix="/smart-money", tags=["smart-money"])
router.include_router(indices_router, prefix="/market", tags=["market-indices"])
router.include_router(news_inbox_router, prefix="/news", tags=["news-inbox"])
router.include_router(review_alerts_router, prefix="/review-alerts", tags=["review-alerts"])
router.include_router(finance_router, prefix="/finance", tags=["finance"])
router.include_router(fno_router, prefix="/fno", tags=["fno"])
router.include_router(health_router, prefix="/health", tags=["health"])
router.include_router(fundamentals_router, prefix="/fundamentals", tags=["fundamentals"])
router.include_router(system_router, prefix="/system", tags=["system"])
router.include_router(holdings_metadata_router, prefix="/holdings-metadata", tags=["holdings-metadata"])
router.include_router(paper_trading_router, prefix="/paper", tags=["paper-trading"])
