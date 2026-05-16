"""
SAMA APEX Bot - Indicators Engine
Port exacto de las funciones Pine Script v6 a Python/NumPy
"""
import math
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from config import (
    AMA_LENGTH, MAJOR_LENGTH, MINOR_LENGTH,
    SLOPE_PERIOD, SLOPE_RANGE, FLAT_THRESHOLD,
    ATR_PERIOD, ATR_MULT, RVOL_PERIOD, RVOL_MIN,
    SESSION_FILTER, SESSION_HOURS_UTC, FUNDING_EXTREME
)


# ─── AMA (Adaptive Moving Average) ───────────────────────────────────────────
def calculate_ama(close: np.ndarray, length: int, min_l: int, maj_l: int) -> np.ndarray:
    """
    Port del Pine Script:
      minAlpha = 2/(min_l+1), majAlpha = 2/(maj_l+1)
      mult = abs(2*src - ll - hh)/(hh - ll) si hh-ll != 0 else 0
      final_alpha = (mult*(minAlpha-majAlpha)+majAlpha)^2
      _ama = (src - _ama[1])*final_alpha + _ama[1]
    """
    min_alpha = 2.0 / (min_l + 1)
    maj_alpha = 2.0 / (maj_l + 1)
    n = len(close)
    ama = np.full(n, np.nan)

    ama_val = np.nan

    for i in range(n):
        if i < length:
            continue

        window = close[i - length: i + 1]   # length+1 velas (igual que Pine: highest(len+1))
        hh = np.max(window)
        ll = np.min(window)

        denom = hh - ll
        mult  = abs(2 * close[i] - ll - hh) / denom if denom != 0 else 0.0

        final       = mult * (min_alpha - maj_alpha) + maj_alpha
        final_alpha = final ** 2

        if math.isnan(ama_val):
            ama_val = close[i]
        else:
            ama_val = (close[i] - ama_val) * final_alpha + ama_val

        ama[i] = ama_val

    return ama


# ─── Slope Angle ─────────────────────────────────────────────────────────────
def calculate_slope(ama: np.ndarray, close: np.ndarray,
                    slope_period: int, slope_init_range: int) -> np.ndarray:
    """
    Port del Pine Script calcslope():
      slope_range = range_1/(highest-lowest)*lowest
      dt = (ama[2]-ama[0])/src * slope_range
      c  = sqrt(1+dt^2)
      angle = round(180*acos(1/c)/pi)
      angle *= sign(dt)  [positivo=bullish, negativo=bearish]
    """
    pi = math.pi
    n  = len(close)
    slopes = np.zeros(n)

    for i in range(slope_period + 2, n):
        if math.isnan(ama[i]) or math.isnan(ama[i - 2]):
            continue

        win_high = np.max(close[i - slope_period + 1: i + 1])
        win_low  = np.min(close[i - slope_period + 1: i + 1])

        diff = win_high - win_low
        if diff == 0:
            continue

        slope_range = slope_init_range / diff * win_low
        dt = (ama[i - 2] - ama[i]) / close[i] * slope_range

        c       = math.sqrt(1 + dt * dt)
        x_angle = round(180 * math.acos(1 / c) / pi)

        slopes[i] = -x_angle if dt > 0 else x_angle

    return slopes


# ─── ATR ─────────────────────────────────────────────────────────────────────
def calculate_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                  period: int = 14) -> np.ndarray:
    """ATR con EMA (mismo que Pine Script ta.atr)"""
    n  = len(close)
    tr = np.zeros(n)
    tr[0] = high[0] - low[0]

    for i in range(1, n):
        tr[i] = max(high[i] - low[i],
                    abs(high[i] - close[i - 1]),
                    abs(low[i]  - close[i - 1]))

    alpha = 1.0 / period
    atr   = np.zeros(n)
    atr[0] = tr[0]
    for i in range(1, n):
        atr[i] = tr[i] * alpha + atr[i - 1] * (1 - alpha)

    return atr


# ─── Relative Volume ──────────────────────────────────────────────────────────
def calculate_rvol(volume: np.ndarray, period: int = 50) -> np.ndarray:
    """RVOL = volume / SMA(volume, period)"""
    n    = len(volume)
    rvol = np.zeros(n)

    for i in range(period, n):
        avg = np.mean(volume[i - period: i])
        rvol[i] = volume[i] / avg if avg > 0 else 0.0

    return rvol


# ─── Trend Classification ─────────────────────────────────────────────────────
def classify_trend(slope: float, flat: int) -> str:
    if slope > flat:
        return "BULL"
    elif slope <= -flat:
        return "BEAR"
    return "CHOP"


# ─── Session Filter ───────────────────────────────────────────────────────────
def is_active_session() -> bool:
    """True si estamos en sesión London o NY (horario UTC)"""
    if not SESSION_FILTER:
        return True
    hour = datetime.now(timezone.utc).hour
    for start, end in SESSION_HOURS_UTC:
        if start <= hour < end:
            return True
    return False


# ─── SAMA Multi-TF Processing ─────────────────────────────────────────────────
def process_sama(df: pd.DataFrame) -> dict:
    """
    Recibe un DataFrame con columnas: open, high, low, close, volume
    Devuelve las métricas SAMA para el último cierre.
    """
    close  = df["close"].values.astype(float)
    high   = df["high"].values.astype(float)
    low    = df["low"].values.astype(float)
    volume = df["volume"].values.astype(float)

    ama    = calculate_ama(close, AMA_LENGTH, MINOR_LENGTH, MAJOR_LENGTH)
    slope  = calculate_slope(ama, close, SLOPE_PERIOD, SLOPE_RANGE)
    atr    = calculate_atr(high, low, close, ATR_PERIOD)
    rvol   = calculate_rvol(volume, RVOL_PERIOD)

    last_ama   = ama[-1]
    last_slope = slope[-1]
    last_atr   = atr[-1]
    last_rvol  = rvol[-1]
    last_close = close[-1]

    return {
        "ama":         last_ama,
        "slope":       last_slope,
        "trend":       classify_trend(last_slope, FLAT_THRESHOLD),
        "atr":         last_atr,
        "rvol":        last_rvol,
        "has_volume":  last_rvol >= RVOL_MIN,
        "upper_band":  last_ama + last_atr * ATR_MULT,
        "lower_band":  last_ama - last_atr * ATR_MULT,
        "close":       last_close,
        # prev values para detección de señal nueva
        "prev_slope":  slope[-2] if len(slope) > 1 else 0.0,
        "prev_trend":  classify_trend(slope[-2], FLAT_THRESHOLD) if len(slope) > 1 else "CHOP",
    }


# ─── Confluence Score (EDGE ESPECIAL) ─────────────────────────────────────────
def confluence_score(local: dict, m1: dict, m2: dict,
                     funding_rate: float = 0.0,
                     session_active: bool = True) -> dict:
    """
    Score 0-100 que pondera la calidad de la señal.
    Mayor score → mayor tamaño de posición y mayor confianza.

    Pesos:
      - Alineación 3 TF:        40 pts
      - Fuerza del slope:       20 pts  (promedio de los 3 slopes)
      - Volumen relativo:       15 pts
      - Sesión activa:          10 pts
      - Funding rate alineado:  15 pts
    """
    lt = local["trend"]
    m1t = m1["trend"]
    m2t = m2["trend"]

    # Sin alineación base → score 0
    if lt == "CHOP" or lt != m1t or lt != m2t:
        return {"score": 0, "direction": None}

    direction = "LONG" if lt == "BULL" else "SHORT"
    score = 0

    # 1. Alineación completa 3 TF (40 pts)
    score += 40

    # 2. Fuerza slopes (20 pts)
    avg_slope = (abs(local["slope"]) + abs(m1["slope"]) + abs(m2["slope"])) / 3
    slope_pts  = min(20.0, (avg_slope / 45.0) * 20)   # 45° = señal muy fuerte
    score += slope_pts

    # 3. RVOL (15 pts)
    avg_rvol = (local["rvol"] + m1["rvol"] + m2["rvol"]) / 3
    if avg_rvol >= RVOL_MIN:
        vol_pts = min(15.0, (avg_rvol - 1.0) * 8)
        score  += vol_pts

    # 4. Sesión activa (10 pts)
    if session_active:
        score += 10

    # 5. Funding rate (15 pts)
    if direction == "LONG":
        if funding_rate < -FUNDING_EXTREME:
            score += 15    # Funding muy negativo = shorts pagan, favorable longs
        elif funding_rate > FUNDING_EXTREME:
            score -= 20    # Funding muy positivo = longs pagan, desfavorable
    else:  # SHORT
        if funding_rate > FUNDING_EXTREME:
            score += 15
        elif funding_rate < -FUNDING_EXTREME:
            score -= 20

    score = max(0, min(100, round(score)))

    return {
        "score":     score,
        "direction": direction,
        "lt":        lt, "m1t": m1t, "m2t": m2t,
        "avg_slope": round(avg_slope, 2),
        "avg_rvol":  round(avg_rvol, 2),
        "funding":   funding_rate,
        "session":   session_active,
    }
