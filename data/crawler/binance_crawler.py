import ccxt
from loguru import logger

from data.crawler.base_crawler import BaseCrawler


class BinanceCrawler(BaseCrawler):
    """
    Crawler for Binance exchange using ccxt.
    Supports both spot and futures markets.
    """

    exchange_id = "binance"

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        market_type: str = "spot",   # 'spot' | 'future'
        testnet: bool = False,
    ):
        self.market_type = market_type
        super().__init__(api_key=api_key, api_secret=api_secret, testnet=testnet)

    def _create_exchange(self) -> ccxt.Exchange:
        options: dict = {
            "defaultType": self.market_type,
            "adjustForTimeDifference": True,
        }

        exchange = ccxt.binance({
            "apiKey": self.api_key,
            "secret": self.api_secret,
            "enableRateLimit": True,
            "options": options,
        })

        if self.testnet:
            exchange.set_sandbox_mode(True)
            logger.warning("[binance] Running in TESTNET mode")

        return exchange
