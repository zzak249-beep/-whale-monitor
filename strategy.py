# -*- coding: utf-8 -*-
"""strategy.py -- ZigZag Institutional Elite V6 (matches Pine script exactly).

Pine logic:
  - ZigZag: ta.pivothigh(high, pivot_len, pivot_len) / ta.pivotlow(low, pivot_len, pivot_len)
  - institucional_vol = volume > (vol_sma20 * vol_mult)   [vol_mult=1.5]
  - LONG:  close crosses above last peak   + institucional_vol + close > open
  - SHORT: close crosses below last valley + institucional_vol + close < open
  - SL (LONG)  = last valley
  - SL (SHORT) = last peak
  - TP = entry + (entry - SL) * rr
"""
from __future__ import annotations
import numpy as np
from dataclasses import dataclass, field
from typing import Optional

# ── Dead session filter (unchanged) ──────────────────────────────────────────
_DEAD_HOURS = {(0,4),(1,4),(2,4),(3,4)}   # UTC 00-04 very low vol

def _in_dead_session() -> bool:
    from datetime import datetime, timezone
    h = datetime.now(timezone.utc).hour
    return h in {0, 1, 2, 3}


@dataclass
class Signal:
    symbol:    str
    side:      str
    price:     float
    sl:        float
    tp:        float
    atr_5m:    float
    score:     int
    vol_ratio: float
    peak:      float
    valley:    float
    reasons:   list = field(default_factory=list)


def _wma(arr: np.ndarray, n: int) -> np.ndarray:
    weights = np.arange(1, n + 1, dtype=np.float64)
    out = np.full(len(arr), np.nan)
    for i in range(n - 1, len(arr)):
        out[i] = np.dot(arr[i - n + 1:i + 1], weights) / weights.sum()
    return out


def _hma(arr: np.ndarray, n: int) -> np.ndarray:
    half = max(1, n // 2)
    sqrt_n = max(1, int(round(n ** 0.5)))
    wma_half = _wma(arr, half)
    wma_full = _wma(arr, n)
    diff = 2 * wma_half - wma_full
    return _wma(diff, sqrt_n)


def _atr(high, low, close, period=14):
    tr = np.maximum(high[1:] - low[1:],
         np.maximum(np.abs(high[1:] - close[:-1]),
                    np.abs(low[1:]  - close[:-1])))
    atr = np.full(len(high), np.nan)
    if len(tr) < period:
        return atr
    atr[period] = tr[:period].mean()
    alpha = 1.0 / period
    for i in range(period + 1, len(high)):
        atr[i] = atr[i-1] * (1 - alpha) + tr[i-1] * alpha
    return atr


def _pivot_high(high: np.ndarray, length: int) -> np.ndarray:
    """Returns array with pivot high values (NaN where no pivot)."""
    n = len(high)
    out = np.full(n, np.nan)
    for i in range(length, n - length):
        window = high[i - length:i + length + 1]
        if high[i] == window.max():
            out[i] = high[i]
    return out


def _pivot_low(low: np.ndarray, length: int) -> np.ndarray:
    """Returns array with pivot low values (NaN where no pivot)."""
    n = len(low)
    out = np.full(n, np.nan)
    for i in range(length, n - length):
        window = low[i - length:i + length + 1]
        if low[i] == window.min():
            out[i] = low[i]
    return out


def get_signal(
    ohlcv_5m:     dict,
    ohlcv_15m:    Optional[dict],
    ohlcv_1h:     Optional[dict],
    symbol:       str,
    open_syms:    set,
    pivot_len:    int   = 5,
    atr_period:   int   = 14,
    atr_mult:     float = 2.0,
    rr:           float = 2.0,
    min_vol_mult: float = 1.5,   # matches Pine vol_mult=1.5
    hma_len:      int   = 50,    # unused but kept for compat
    ft_period:    int   = 25,    # unused but kept for compat
    min_atr_pct:  float = 0.10,
    min_score:    int   = 3,
) -> tuple[Optional[Signal], str]:

    if not ohlcv_5m:
        return None, "no_data"

    o  = ohlcv_5m["open"]
    h  = ohlcv_5m["high"]
    l  = ohlcv_5m["low"]
    c  = ohlcv_5m["close"]
    v  = ohlcv_5m["volume"]

    if len(c) < pivot_len * 2 + 20:
        return None, "too_short"

    # ── ATR filter ────────────────────────────────────────────────────────────
    atr_arr = _atr(h, l, c, atr_period)
    atr_val = float(atr_arr[-2]) if not np.isnan(atr_arr[-2]) else 0.0
    price   = float(c[-1])

    if atr_val <= 0:
        return None, "atr_zero"
    if atr_val / price * 100 < min_atr_pct:
        return None, f"atr_low={atr_val/price*100:.3f}%"

    # ── Volume: institucional_vol = volume > vol_sma20 * vol_mult ─────────────
    if len(v) < 22:
        return None, "vol_short"
    vol_sma20   = float(np.mean(v[-21:-1]))   # SMA(volume, 20) at bar[-1]
    last_vol    = float(v[-1])
    vol_ratio   = last_vol / vol_sma20 if vol_sma20 > 0 else 0.0
    inst_vol    = vol_ratio >= min_vol_mult

    if not inst_vol:
        return None, f"vol_low={vol_ratio:.2f}"

    # ── Pivot High / Low (ZigZag) ─────────────────────────────────────────────
    ph_arr = _pivot_high(h, pivot_len)
    pl_arr = _pivot_low(l,  pivot_len)

    # Find the most recent non-NaN peak and valley (before current bar)
    peak   = np.nan
    valley = np.nan
    for i in range(len(ph_arr) - 2, -1, -1):
        if not np.isnan(ph_arr[i]):
            peak = float(ph_arr[i])
            break
    for i in range(len(pl_arr) - 2, -1, -1):
        if not np.isnan(pl_arr[i]):
            valley = float(pl_arr[i])
            break

    if np.isnan(peak) or np.isnan(valley):
        return None, "no_pivot"

    # ── Candle body direction ─────────────────────────────────────────────────
    last_close = float(c[-1])
    last_open  = float(o[-1])
    prev_close = float(c[-2])

    bullish_body = last_close > last_open
    bearish_body = last_close < last_open

    # ── Crossover / Crossunder (Pine: ta.crossover(close, peak)) ─────────────
    # crossover: prev_close <= peak and last_close > peak
    long_cross  = (prev_close <= peak)   and (last_close > peak)   and bullish_body
    # crossunder: prev_close >= valley and last_close < valley
    short_cross = (prev_close >= valley) and (last_close < valley) and bearish_body

    if not long_cross and not short_cross:
        return None, "no_breakout"

    # ── Build signal ──────────────────────────────────────────────────────────
    if long_cross:
        side    = "BUY"
        sl      = valley                            # Pine: sl = valley
        tp      = last_close + (last_close - sl) * rr  # Pine: tp = close + (close - sl) * tp_mult
        reasons = [f"zigzag_break_high>{peak:.4f}", f"vol×{vol_ratio:.1f}", "bull_body"]
    else:
        side    = "SELL"
        sl      = peak                              # Pine: sl = peak
        tp      = last_close - (sl - last_close) * rr
        reasons = [f"zigzag_break_low<{valley:.4f}", f"vol×{vol_ratio:.1f}", "bear_body"]

    # Validate SL/TP geometry
    if side == "BUY":
        if sl >= last_close or tp <= last_close:
            return None, "sl_tp_invalid"
    else:
        if sl <= last_close or tp >= last_close:
            return None, "sl_tp_invalid"

    sl_pct = abs(last_close - sl) / last_close * 100
    if sl_pct < 0.05:
        return None, "sl_too_tight"
    if sl_pct > 15.0:
        return None, f"sl_too_wide={sl_pct:.1f}%"

    # ── Score (simple: 1 base + bonuses) ─────────────────────────────────────
    score = 3  # base: pivot break + inst_vol + candle body

    # Bonus: 15m confirms trend
    if ohlcv_15m and len(ohlcv_15m.get("close", [])) >= 30:
        c15 = ohlcv_15m["close"]
        o15 = ohlcv_15m["open"]
        # Last 15m candle same direction
        if side == "BUY"  and float(c15[-1]) > float(o15[-1]): score += 1
        if side == "SELL" and float(c15[-1]) < float(o15[-1]): score += 1

    # Bonus: strong vol
    if vol_ratio >= min_vol_mult * 1.5:
        score += 1

    # Bonus: ATR expanding (volatility increasing)
    if not np.isnan(atr_arr[-3]) and atr_val > float(atr_arr[-3]):
        score += 1

    if score < min_score:
        return None, f"score_low={score}"

    return Signal(
        symbol    = symbol,
        side      = side,
        price     = last_close,
        sl        = sl,
        tp        = tp,
        atr_5m    = atr_val,
        score     = score,
        vol_ratio = vol_ratio,
        peak      = peak,
        valley    = valley,
        reasons   = reasons,
    ), "ok"


def check_trail_exit(
    ohlcv_5m:   dict,
    ohlcv_15m:  Optional[dict],
    trade_side: str,
    pivot_len:  int   = 5,
    hma_len:    int   = 50,
    ft_period:  int   = 25,
    peak_r:     float = 0.0,
) -> Optional[str]:
    """Trail exit: exit when price breaks back through the opposite pivot."""
    if not ohlcv_5m or len(ohlcv_5m.get("close", [])) < pivot_len * 2 + 5:
        return None

    c = ohlcv_5m["close"]
    h = ohlcv_5m["high"]
    l = ohlcv_5m["low"]
    o = ohlcv_5m["open"]

    # Only trail-exit after meaningful gain
    if peak_r < 1.0:
        return None

    ph_arr = _pivot_high(h, pivot_len)
    pl_arr = _pivot_low(l,  pivot_len)

    last_close = float(c[-1])
    prev_close = float(c[-2])

    if trade_side == "BUY":
        # Find most recent valley
        for i in range(len(pl_arr) - 2, -1, -1):
            if not np.isnan(pl_arr[i]):
                valley = float(pl_arr[i])
                # Exit if price breaks back below recent valley
                if prev_close >= valley and last_close < valley and float(c[-1]) < float(o[-1]):
                    return "TRAIL_ZZ"
                break
    else:
        # Find most recent peak
        for i in range(len(ph_arr) - 2, -1, -1):
            if not np.isnan(ph_arr[i]):
                peak = float(ph_arr[i])
                if prev_close <= peak and last_close > peak and float(c[-1]) > float(o[-1]):
                    return "TRAIL_ZZ"
                break

    return None
