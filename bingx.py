import time
import hmac
import hashlib
import requests
import config


# ─────────────────────────────────────────────────────────────
#  FIRMA HMAC SHA256 (requerida por BingX)
# ─────────────────────────────────────────────────────────────

def _sign(payload: dict) -> str:
    query_string = "&".join([f"{k}={v}" for k, v in sorted(payload.items())])
    return hmac.new(
        config.BINGX_SECRET_KEY.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _headers() -> dict:
    return {"X-BX-APIKEY": config.BINGX_API_KEY}


# ─────────────────────────────────────────────────────────────
#  DATOS DE MERCADO
# ─────────────────────────────────────────────────────────────

def get_klines(symbol: str, timeframe: str, limit: int = 150) -> list:
    """Obtiene las velas OHLCV desde BingX Swap V3."""
    url = f"{config.BASE_URL}/openApi/swap/v3/quote/klines"
    params = {"symbol": symbol, "interval": timeframe, "limit": limit}
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()["data"]


def get_account_balance() -> dict:
    """Retorna el balance de la cuenta de futuros."""
    url = f"{config.BASE_URL}/openApi/swap/v2/user/balance"
    payload = {"timestamp": int(time.time() * 1000)}
    payload["signature"] = _sign(payload)
    resp = requests.get(url, headers=_headers(), params=payload, timeout=10)
    resp.raise_for_status()
    return resp.json().get("data", {})


def get_open_positions(symbol: str) -> list:
    """Consulta posiciones abiertas para el símbolo dado."""
    url = f"{config.BASE_URL}/openApi/swap/v2/user/positions"
    payload = {"symbol": symbol, "timestamp": int(time.time() * 1000)}
    payload["signature"] = _sign(payload)
    resp = requests.get(url, headers=_headers(), params=payload, timeout=10)
    resp.raise_for_status()
    return resp.json().get("data", [])


def set_leverage(symbol: str, leverage: int) -> dict:
    """Establece el apalancamiento para el símbolo."""
    url = f"{config.BASE_URL}/openApi/swap/v2/trade/leverage"
    payload = {
        "symbol":    symbol,
        "side":      "LONG",
        "leverage":  leverage,
        "timestamp": int(time.time() * 1000),
    }
    payload["signature"] = _sign(payload)
    resp = requests.post(url, headers=_headers(), data=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()


# ─────────────────────────────────────────────────────────────
#  COLOCACIÓN DE ÓRDENES
# ─────────────────────────────────────────────────────────────

def place_order(
    symbol:      str,
    side:        str,   # "BUY" | "SELL"
    order_type:  str,   # "MARKET" | "LIMIT"
    quantity:    float,
    price:       float = None,
    stop_loss:   float = None,
    take_profit: float = None,
) -> dict:
    """
    Coloca una orden en BingX Swap V2.
    Retorna el JSON de respuesta completo.
    """
    url = f"{config.BASE_URL}/openApi/swap/v2/trade/order"
    payload = {
        "symbol":       symbol,
        "side":         side,
        "positionSide": "LONG" if side == "BUY" else "SHORT",
        "type":         order_type,
        "quantity":     quantity,
        "timestamp":    int(time.time() * 1000),
    }
    if price:
        payload["price"] = price
    if stop_loss:
        payload["stopLoss"]   = f'{{"type":"STOP_MARKET","stopPrice":{stop_loss},"price":{stop_loss}}}'
    if take_profit:
        payload["takeProfit"] = f'{{"type":"TAKE_PROFIT_MARKET","stopPrice":{take_profit},"price":{take_profit}}}'

    payload["signature"] = _sign(payload)
    resp = requests.post(url, headers=_headers(), data=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()


def close_position(symbol: str, side: str, quantity: float) -> dict:
    """
    Cierra una posición existente con orden MARKET inversa.
    side = "BUY" para cerrar SHORT | "SELL" para cerrar LONG
    """
    url = f"{config.BASE_URL}/openApi/swap/v2/trade/order"
    payload = {
        "symbol":       symbol,
        "side":         side,
        "positionSide": "LONG" if side == "SELL" else "SHORT",
        "type":         "MARKET",
        "quantity":     quantity,
        "reduceOnly":   True,
        "timestamp":    int(time.time() * 1000),
    }
    payload["signature"] = _sign(payload)
    resp = requests.post(url, headers=_headers(), data=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()
