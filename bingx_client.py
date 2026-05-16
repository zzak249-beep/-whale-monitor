"""
SAMA APEX Bot - BingX Perpetual Futures Client
Implementa todas las llamadas REST necesarias para operar en BingX Swap
"""
import hmac
import hashlib
import time
import json
import asyncio
import aiohttp
import logging
import pandas as pd
from urllib.parse import urlencode
from config import BINGX_API_KEY, BINGX_SECRET_KEY, BINGX_BASE_URL, LEVERAGE

logger = logging.getLogger(__name__)

# Mapeo de timeframes legibles → formato BingX
TF_MAP = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m",
    "30m": "30m", "1h": "1h", "2h": "2h", "4h": "4h",
    "6h": "6h", "12h": "12h", "1d": "1d",
}


def _sign(params: dict, secret: str) -> str:
    """HMAC SHA256 signature para BingX"""
    query = urlencode(sorted(params.items()))
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


def _timestamp() -> int:
    return int(time.time() * 1000)


class BingXClient:
    def __init__(self):
        self.session: aiohttp.ClientSession | None = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()

    # ─── Internal HTTP helpers ────────────────────────────────────────────────

    async def _get(self, path: str, params: dict = None, auth: bool = False) -> dict:
        params = params or {}
        if auth:
            params["timestamp"] = _timestamp()
            params["signature"] = _sign(params, BINGX_SECRET_KEY)
        headers = {"X-BX-APIKEY": BINGX_API_KEY} if auth else {}
        url = BINGX_BASE_URL + path
        async with self.session.get(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as r:
            data = await r.json()
            if data.get("code") != 0:
                logger.error(f"BingX GET error {path}: {data}")
            return data

    async def _post(self, path: str, params: dict = None) -> dict:
        params = params or {}
        params["timestamp"] = _timestamp()
        params["signature"] = _sign(params, BINGX_SECRET_KEY)
        headers = {"X-BX-APIKEY": BINGX_API_KEY}
        url = BINGX_BASE_URL + path
        async with self.session.post(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as r:
            data = await r.json()
            if data.get("code") != 0:
                logger.error(f"BingX POST error {path}: {data}")
            return data

    async def _delete(self, path: str, params: dict = None) -> dict:
        params = params or {}
        params["timestamp"] = _timestamp()
        params["signature"] = _sign(params, BINGX_SECRET_KEY)
        headers = {"X-BX-APIKEY": BINGX_API_KEY}
        url = BINGX_BASE_URL + path
        async with self.session.delete(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as r:
            return await r.json()

    # ─── Market Data ──────────────────────────────────────────────────────────

    async def get_klines(self, symbol: str, interval: str, limit: int = 300) -> pd.DataFrame:
        """Devuelve DataFrame con OHLCV para el símbolo/intervalo"""
        bx_interval = TF_MAP.get(interval, interval)
        data = await self._get("/openApi/swap/v2/quote/klines", {
            "symbol": symbol,
            "interval": bx_interval,
            "limit": min(limit, 1440),
        })
        if data.get("code") != 0 or not data.get("data"):
            return pd.DataFrame()

        rows = []
        for c in data["data"]:
            rows.append({
                "time":   int(c["time"]),
                "open":   float(c["open"]),
                "high":   float(c["high"]),
                "low":    float(c["low"]),
                "close":  float(c["close"]),
                "volume": float(c["volume"]),
            })
        df = pd.DataFrame(rows).sort_values("time").reset_index(drop=True)
        return df

    async def get_ticker(self, symbol: str) -> dict:
        """Precio actual y 24h stats"""
        data = await self._get("/openApi/swap/v2/quote/ticker", {"symbol": symbol})
        return data.get("data", {})

    async def get_funding_rate(self, symbol: str) -> float:
        """Funding rate actual del símbolo"""
        data = await self._get("/openApi/swap/v2/quote/premiumIndex", {"symbol": symbol})
        try:
            return float(data["data"]["lastFundingRate"])
        except (KeyError, TypeError, ValueError):
            return 0.0

    async def get_orderbook_depth(self, symbol: str) -> dict:
        """Top 5 libro de órdenes para detección de liquidez"""
        data = await self._get("/openApi/swap/v2/quote/depth", {"symbol": symbol, "limit": 5})
        return data.get("data", {})

    # ─── Account ──────────────────────────────────────────────────────────────

    async def get_balance(self) -> float:
        """Balance USDT disponible"""
        data = await self._get("/openApi/swap/v2/user/balance", {}, auth=True)
        try:
            assets = data["data"]["balance"]
            # BingX puede devolver la estructura de varias formas
            if isinstance(assets, list):
                for a in assets:
                    if a.get("asset") == "USDT":
                        return float(a.get("availableMargin", a.get("balance", 0)))
            elif isinstance(assets, dict):
                return float(assets.get("availableMargin", assets.get("equity", 0)))
        except (KeyError, TypeError):
            pass
        return 0.0

    async def get_positions(self, symbol: str = None) -> list:
        """Posiciones abiertas (filtradas por símbolo si se especifica)"""
        params = {}
        if symbol:
            params["symbol"] = symbol
        data = await self._get("/openApi/swap/v2/user/positions", params, auth=True)
        positions = data.get("data", []) or []
        return [p for p in positions if float(p.get("positionAmt", 0)) != 0]

    async def get_open_orders(self, symbol: str) -> list:
        """Órdenes abiertas para un símbolo"""
        data = await self._get("/openApi/swap/v2/trade/openOrders", {"symbol": symbol}, auth=True)
        return data.get("data", {}).get("orders", [])

    # ─── Trading ──────────────────────────────────────────────────────────────

    async def set_leverage(self, symbol: str, leverage: int) -> bool:
        """Configura apalancamiento antes de abrir posición"""
        for side in ["LONG", "SHORT"]:
            res = await self._post("/openApi/swap/v2/trade/leverage", {
                "symbol":   symbol,
                "side":     side,
                "leverage": leverage,
            })
            if res.get("code") != 0:
                logger.warning(f"set_leverage {symbol} {side}: {res}")
        return True

    async def place_market_order(self, symbol: str, side: str, quantity: float,
                                  position_side: str = "LONG") -> dict:
        """
        side: BUY / SELL
        position_side: LONG / SHORT (modo one-way se puede omitir)
        """
        params = {
            "symbol":       symbol,
            "side":         side,
            "positionSide": position_side,
            "type":         "MARKET",
            "quantity":     round(quantity, 4),
        }
        return await self._post("/openApi/swap/v2/trade/order", params)

    async def place_tp_sl_order(self, symbol: str, side: str, quantity: float,
                                 stop_price: float, order_type: str,
                                 position_side: str = "LONG") -> dict:
        """
        order_type: STOP_MARKET / TAKE_PROFIT_MARKET
        """
        params = {
            "symbol":       symbol,
            "side":         side,
            "positionSide": position_side,
            "type":         order_type,
            "stopPrice":    round(stop_price, 4),
            "quantity":     round(quantity, 4),
            "closePosition": "true",
        }
        return await self._post("/openApi/swap/v2/trade/order", params)

    async def cancel_all_orders(self, symbol: str) -> dict:
        """Cancela todas las órdenes abiertas de un símbolo"""
        return await self._delete("/openApi/swap/v2/trade/allOpenOrders", {"symbol": symbol})

    async def close_position(self, symbol: str, position_side: str, quantity: float) -> dict:
        """Cierra posición a mercado"""
        side = "SELL" if position_side == "LONG" else "BUY"
        return await self.place_market_order(symbol, side, quantity, position_side)

    # ─── Symbol Info ──────────────────────────────────────────────────────────

    async def get_symbol_info(self, symbol: str) -> dict:
        """Devuelve minQty, stepSize, pricePrecision del símbolo"""
        data = await self._get("/openApi/swap/v2/quote/contracts")
        if data.get("code") != 0:
            return {}
        for c in data.get("data", []):
            if c.get("symbol") == symbol:
                return c
        return {}

    async def round_quantity(self, symbol: str, raw_qty: float) -> float:
        """Ajusta quantity al stepSize del símbolo"""
        info = await self.get_symbol_info(symbol)
        step = float(info.get("quantityPrecision", 3))
        factor = 10 ** int(step)
        return math.floor(raw_qty * factor) / factor

    # ─── Update Trailing Stop ─────────────────────────────────────────────────

    async def update_trailing_stop(self, symbol: str, position_side: str,
                                    new_sl: float, quantity: float) -> dict:
        """Cancela SL anterior y coloca uno nuevo (trailing manual)"""
        await self.cancel_all_orders(symbol)
        side = "SELL" if position_side == "LONG" else "BUY"
        return await self.place_tp_sl_order(
            symbol, side, quantity, new_sl, "STOP_MARKET", position_side
        )


import math  # se usa en round_quantity
