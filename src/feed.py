"""Market data ingestion layer with resilient connection pooling and exponential backoff."""

import asyncio
import logging
import random
from typing import Dict, List, Optional
import httpx

from src.models import PriceSnapshot

logger = logging.getLogger(__name__)

# Constants
DEFAULT_TIMEOUT_SECONDS: float = 10.0
MAX_BACKOFF_SECONDS: float = 60.0
INITIAL_BACKOFF_SECONDS: float = 1.0
BACKOFF_FACTOR: float = 2.0
JITTER_RATIO: float = 0.2

# Public Endpoints
BINANCE_PRICE_URL: str = "https://api.binance.com/api/v3/ticker/price"
BINANCE_24HR_URL: str = "https://api.binance.com/api/v3/ticker/24hr"
COINGECKO_PRICE_URL: str = "https://api.coingecko.com/api/v3/simple/price"

# Mapping for CoinGecko fallback (base asset to coingecko id)
COINGECKO_SYMBOL_MAP: Dict[str, str] = {
    "BTCUSDT": "bitcoin",
    "ETHUSDT": "ethereum",
    "SOLUSDT": "solana",
    "BNBUSDT": "binancecoin",
    "ADAUSDT": "cardano",
    "DOGEUSDT": "dogecoin",
    "XRPUSDT": "ripple",
}


class MarketFeed:
    """Async market data fetcher supporting Binance with CoinGecko fallback."""

    def __init__(self, client: Optional[httpx.AsyncClient] = None) -> None:
        self._external_client = client is not None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(DEFAULT_TIMEOUT_SECONDS),
            headers={"User-Agent": "CryptoMonitorDaemon/1.0"}
        )
        self._consecutive_failures: int = 0

    async def close(self) -> None:
        """Close HTTP client session cleanly."""
        if not self._external_client and not self._client.is_closed:
            await self._client.aclose()

    async def fetch_prices(self, symbols: List[str]) -> Dict[str, PriceSnapshot]:
        """
        Fetch current market snapshots for target symbols.
        Resilient: retries with exponential backoff on failure and uses fallback.
        """
        if not symbols:
            return {}

        target_set = {s.upper() for s in symbols}

        # Try Binance primary feed
        try:
            snapshots = await self._fetch_binance(target_set)
            if self._consecutive_failures > 0:
                logger.info("Successfully recovered market feed connection to Binance.")
                self._consecutive_failures = 0
            return snapshots
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            self._consecutive_failures += 1
            backoff_delay = self._calculate_backoff()
            logger.warning(
                "Binance feed request failed (%s). Failure count: %d. Attempting CoinGecko fallback. Backoff: %.1fs",
                exc,
                self._consecutive_failures,
                backoff_delay,
            )
            await asyncio.sleep(backoff_delay)

        # Fallback to CoinGecko
        try:
            fallback_snapshots = await self._fetch_coingecko(target_set)
            if fallback_snapshots:
                logger.info("Successfully fetched %d snapshot(s) from CoinGecko fallback.", len(fallback_snapshots))
                return fallback_snapshots
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            logger.error("CoinGecko fallback also failed (%s). Returning empty snapshot set.", exc)

        return {}

    async def _fetch_binance(self, symbols: set[str]) -> Dict[str, PriceSnapshot]:
        """Fetch batch prices and 24h ticker data from Binance."""
        snapshots: Dict[str, PriceSnapshot] = {}

        # 1. Fetch prices
        price_resp = await self._client.get(BINANCE_PRICE_URL)
        price_resp.raise_for_status()
        price_data = price_resp.json()

        for item in price_data:
            sym = item.get("symbol")
            if sym in symbols:
                price = float(item["price"])
                snapshots[sym] = PriceSnapshot(symbol=sym, price=price)

        # 2. Fetch 24hr stats to get 24h change percent
        try:
            stats_resp = await self._client.get(BINANCE_24HR_URL)
            if stats_resp.status_code == 200:
                stats_data = stats_resp.json()
                for item in stats_data:
                    sym = item.get("symbol")
                    if sym in snapshots:
                        change_percent = float(item.get("priceChangePercent", 0.0))
                        snapshots[sym].change_24h_percent = change_percent
        except Exception as e:
            logger.debug("Failed to fetch 24hr ticker stats from Binance: %s", e)

        return snapshots

    async def _fetch_coingecko(self, symbols: set[str]) -> Dict[str, PriceSnapshot]:
        """Fallback poller using CoinGecko public API."""
        cg_ids: Dict[str, str] = {}
        for sym in symbols:
            if sym in COINGECKO_SYMBOL_MAP:
                cg_ids[COINGECKO_SYMBOL_MAP[sym]] = sym

        if not cg_ids:
            return {}

        params = {
            "ids": ",".join(cg_ids.keys()),
            "vs_currencies": "usd",
            "include_24hr_change": "true",
        }

        resp = await self._client.get(COINGECKO_PRICE_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

        snapshots: Dict[str, PriceSnapshot] = {}
        for cg_id, sym in cg_ids.items():
            if cg_id in data and "usd" in data[cg_id]:
                price = float(data[cg_id]["usd"])
                change_24h = data[cg_id].get("usd_24h_change")
                snapshots[sym] = PriceSnapshot(
                    symbol=sym,
                    price=price,
                    change_24h_percent=float(change_24h) if change_24h is not None else None,
                )

        return snapshots

    def _calculate_backoff(self) -> float:
        """Calculate exponential backoff duration with randomized jitter."""
        factor = BACKOFF_FACTOR ** min(self._consecutive_failures - 1, 6)
        base = min(INITIAL_BACKOFF_SECONDS * factor, MAX_BACKOFF_SECONDS)
        jitter = random.uniform(-JITTER_RATIO * base, JITTER_RATIO * base)
        return max(1.0, min(base + jitter, MAX_BACKOFF_SECONDS))
