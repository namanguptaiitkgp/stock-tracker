from datetime import date
from functools import lru_cache

from kiteconnect import KiteConnect

from app.config import get_settings


class KiteService:
    def __init__(self, api_key: str, api_secret: str) -> None:
        self.api_secret = api_secret
        self.kite = KiteConnect(api_key=api_key)

    def get_login_url(self) -> str:
        return self.kite.login_url()

    def generate_session(self, request_token: str) -> dict:
        data = self.kite.generate_session(request_token, api_secret=self.api_secret)
        self.kite.set_access_token(data["access_token"])
        return data

    def set_access_token(self, token: str) -> None:
        self.kite.set_access_token(token)

    def get_holdings(self) -> list:
        return self.kite.holdings()

    def get_positions(self) -> dict:
        return self.kite.positions()

    def get_quote(self, instruments: list[str]) -> dict:
        return self.kite.quote(instruments)

    def place_order(self, **kwargs) -> str:
        return self.kite.place_order(**kwargs)

    def get_order_history(self, order_id: str) -> list:
        return self.kite.order_history(order_id)

    def get_historical_data(
        self,
        instrument_token: int,
        from_date: date,
        to_date: date,
        interval: str,
    ) -> list:
        return self.kite.historical_data(instrument_token, from_date, to_date, interval)


@lru_cache
def get_kite_service() -> KiteService:
    settings = get_settings()
    return KiteService(
        api_key=settings.KITE_API_KEY,
        api_secret=settings.KITE_API_SECRET,
    )
