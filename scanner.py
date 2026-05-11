"""
scanner.py — Escaneo multi-moneda de todos los futuros de BingX.

Flujo por ciclo:
  1. Obtener lista completa de contratos disponibles en BingX.
  2. Filtrar por volumen 24h mínimo (evitar pares sin liquidez).
  3. Por cada par: obtener velas + aplicar Quantum Edge V36.
  4. Puntuar cada par según la fuerza de la señal.
  5. Retornar las mejores oportunidades ordenadas por score.
"""

import time
import requests
import pandas as pd
import config
from indicators import apply_quantum_edge


# ─────────────────────────────────────────────────────────────
#  OBTENER TODOS LOS CONTRATOS DE BINGX
# ─────────────────────────────────────────────────────────────

def get_all_contracts() -> list[str]:
    """
    Consulta el endpoint público de contratos de BingX y retorna
    una lista de símbolos (ej: ['BTC-USDT', 'ETH-USDT', ...]).
    Filtra automáticamente los pares sin suficiente volumen.
    """
    url = f"{config.BASE_URL}/openApi/swap/v2/quote/contracts"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json().get("data", [])

        symbols = []
        for c in data:
            symbol = c.get("symbol", "")
            # Solo pares USDT, activos, con volumen mínimo
            if (
                symbol.endswith("-USDT")
                and c.get("status", 0) == 1          # contrato activo
            ):
                symbols.append(symbol)

        print(f"[SCANNER] ✅ {len(symbols)} contratos activos USDT encontrados")
        return symbols

    except Exception as e:
        print(f"[SCANNER] ❌ Error obteniendo contratos: {e}")
        return []


# ─────────────────────────────────────────────────────────────
#  FILTRO DE LIQUIDEZ POR VOLUMEN 24H
# ─────────────────────────────────────────────────────────────

def get_tickers_volume() -> dict[str, float]:
    """
    Obtiene el volumen 24h de todos los pares en una sola llamada.
    Retorna dict {symbol: volume_usdt_24h}.
    """
    url = f"{config.BASE_URL}/openApi/swap/v2/quote/ticker"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        tickers = resp.json().get("data", [])
        return {
            t["symbol"]: float(t.get("quoteVolume", 0))
            for t in tickers
            if "symbol" in t
        }
    except Exception as e:
        print(f"[SCANNER] ⚠️ Error obteniendo volúmenes: {e}")
        return {}


def filter_by_volume(symbols: list[str], min_volume_usdt: float) -> list[str]:
    """Filtra símbolos con volumen 24h inferior al mínimo configurado."""
    volumes = get_tickers_volume()
    filtered = [
        s for s in symbols
        if volumes.get(s, 0) >= min_volume_usdt
    ]
    print(f"[SCANNER] 💧 {len(filtered)} pares con volumen ≥ ${min_volume_usdt:,.0f} USDT/24h")
    return filtered


# ─────────────────────────────────────────────────────────────
#  ANÁLISIS DE UN SÍMBOLO
# ─────────────────────────────────────────────────────────────

def _get_klines(symbol: str, timeframe: str, limit: int = 150) -> pd.DataFrame | None:
    """Obtiene velas OHLCV para un símbolo. Retorna None si falla."""
    url = f"{config.BASE_URL}/openApi/swap/v3/quote/klines"
    params = {"symbol": symbol, "interval": timeframe, "limit": limit}
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        raw = resp.json().get("data", [])
        if len(raw) < 50:
            return None
        df = pd.DataFrame(raw)
        df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
        df = df[["open", "high", "low", "close", "volume"]].astype(float)
        return df
    except Exception:
        return None


def score_symbol(symbol: str, timeframe: str, pivot_len: int = 5) -> dict | None:
    """
    Analiza un símbolo con Quantum Edge V36 y retorna un dict con:
      - symbol, signal (LONG/SHORT/NONE), score (0–100), indicadores clave.
    Retorna None si no hay suficientes datos.
    """
    df = _get_klines(symbol, timeframe)
    if df is None:
        return None

    try:
        df = apply_quantum_edge(df, pivot_len=pivot_len)
        if len(df) < 3:
            return None

        current = df.iloc[-1]
        prev    = df.iloc[-2]

        adx  = float(current["adx"])
        cvd  = float(current["cvd"])
        atr  = float(current["atr"])
        close = float(current["close"])

        cruz_alcista = (current["ema7"] > current["ema17"]) and (prev["ema7"] <= prev["ema17"])
        cruz_bajista = (current["ema7"] < current["ema17"]) and (prev["ema7"] >= prev["ema17"])

        long_conds  = [
            cruz_alcista,
            float(current["low"]) < float(current["valley"]),
            bool(current["is_inst_vol"]),
            adx > config.ADX_MIN,
            cvd > 0,
            close < float(current["vwap"]),
        ]
        short_conds = [
            cruz_bajista,
            float(current["high"]) > float(current["peak"]),
            bool(current["is_inst_vol"]),
            adx > config.ADX_MIN,
            cvd < 0,
            close > float(current["vwap"]),
        ]

        long_score  = sum(long_conds)
        short_score = sum(short_conds)
        max_score   = len(long_conds)  # 6

        if long_score >= 4:
            signal = "LONG"
            score  = round((long_score / max_score) * 100)
        elif short_score >= 4:
            signal = "SHORT"
            score  = round((short_score / max_score) * 100)
        else:
            signal = "NONE"
            score  = max(
                round((long_score / max_score) * 100),
                round((short_score / max_score) * 100),
            )

        # Calcular SL / TP estimados
        sl = tp = None
        if signal == "LONG":
            sl = round(float(current["valley"]) - atr * 0.8, 4)
            tp = round(float(current["vwap"]), 4)
        elif signal == "SHORT":
            sl = round(float(current["peak"]) + atr * 0.8, 4)
            tp = round(float(current["vwap"]), 4)

        rr = None
        if sl and tp and abs(close - sl) > 0:
            rr = round(abs(tp - close) / abs(close - sl), 2)

        return {
            "symbol":    symbol,
            "signal":    signal,
            "score":     score,
            "price":     close,
            "adx":       round(adx, 1),
            "cvd":       round(cvd, 2),
            "atr":       round(atr, 6),
            "sl":        sl,
            "tp":        tp,
            "rr":        rr,
            "long_hits":  long_score,
            "short_hits": short_score,
        }

    except Exception as e:
        print(f"[SCANNER] ⚠️ Error analizando {symbol}: {e}")
        return None


# ─────────────────────────────────────────────────────────────
#  ESCANEO COMPLETO
# ─────────────────────────────────────────────────────────────

def run_full_scan(
    timeframe:      str   = None,
    min_volume:     float = None,
    top_n:          int   = None,
    delay_ms:       int   = 120,   # ms entre requests (respetar rate-limit)
) -> dict:
    """
    Escanea TODOS los futuros USDT de BingX.
    Retorna un dict con:
      - 'signals':  lista de pares con señal LONG o SHORT (score ≥ 4/6 condiciones)
      - 'top':      top_n pares por score (con o sin señal)
      - 'total':    total de pares escaneados
      - 'longs':    número de señales LONG
      - 'shorts':   número de señales SHORT
    """
    tf      = timeframe  or config.TIMEFRAME
    min_vol = min_volume or config.MIN_VOLUME_24H
    top_n   = top_n      or config.TOP_N_RESULTS

    print(f"\n[SCANNER] 🚀 Iniciando escaneo completo — TF={tf}")

    # 1. Todos los contratos activos
    symbols = get_all_contracts()
    if not symbols:
        return {"signals": [], "top": [], "total": 0, "longs": 0, "shorts": 0}

    # 2. Filtrar por volumen mínimo
    symbols = filter_by_volume(symbols, min_vol)

    # 3. Analizar cada símbolo
    results = []
    total = len(symbols)
    for i, sym in enumerate(symbols, 1):
        res = score_symbol(sym, tf, pivot_len=config.PIVOT_LEN)
        if res:
            results.append(res)
        if i % 20 == 0:
            print(f"[SCANNER] 🔍 {i}/{total} escaneados...")
        time.sleep(delay_ms / 1000)

    # 4. Ordenar por score descendente
    results.sort(key=lambda x: x["score"], reverse=True)

    signals = [r for r in results if r["signal"] in ("LONG", "SHORT")]
    longs   = [r for r in signals if r["signal"] == "LONG"]
    shorts  = [r for r in signals if r["signal"] == "SHORT"]

    print(f"[SCANNER] ✅ Escaneo completo: {len(results)} analizados | "
          f"🟢 {len(longs)} LONG | 🔴 {len(shorts)} SHORT")

    return {
        "signals": signals,
        "top":     results[:top_n],
        "total":   len(results),
        "longs":   len(longs),
        "shorts":  len(shorts),
    }
