# -*- coding: utf-8 -*-
"""strategy.py -- Phantom Edge Bot: ZigZag puro + Supertrend(15m).

ZigZag real (no pivot simple):
  - Detecta swings con desviacion minima % del precio
  - Rastrea cadena de HH/HL (uptrend) y LH/LL (downtrend)
  - LONG  cuando precio rompe el ultimo swing HIGH con Supertrend alcista
  - SHORT cuando precio rompe el ultimo swing LOW  con Supertrend bajista
  - SL debajo del ultimo swing LOW (LONG) / encima del ultimo swing HIGH (SHORT)
    → SL natural en estructura, no ATR fijo

Ventaja vs pivot simple:
  - ZigZag filtra ruido con min_deviation% — ignora microswings
  - SL en estructura real (ultimo swing) = nivel que el mercado ha respetado
  - Detecta mercados en trending vs ranging por numero de swings recientes
"""
from __future__ import annotations
import numpy as np
from dataclasses import dataclass


@dataclass
class Signal:
    symbol:      str
    side:        str      # "BUY" | "SELL"
    price:       float
    sl:          float    # last swing low (LONG) / high (SHORT)
    tp:          float    # sl_dist * rr
    atr_5m:      float
    zz_high:     float    # last confirmed ZigZag high
    zz_low:      float    # last confirmed ZigZag low
    zz_trend:    str      # "UP" | "DOWN" | "FLAT"
    st_bull_15m: bool
    score:       int      # 0-10
    vol_ratio:   float
    # compat aliases for pos_manager / notifier
    delta1:      float = 0.0
    delta2:      float = 0.0
    atr:         float = 0.0   # filled = atr_5m post-init

    def __post_init__(self):
        self.atr    = self.atr_5m
        self.delta1 = self.zz_high
        self.delta2 = self.zz_low


# ═══════════════════════════════════════════════════════════════════════
# ZIGZAG ENGINE
# ═══════════════════════════════════════════════════════════════════════

def compute_zigzag(
    highs: np.ndarray,
    lows:  np.ndarray,
    min_deviation: float = 0.5,   # % mínimo para nuevo swing
) -> tuple[list[tuple[int, float, str]], str]:
    """
    Returns:
      swings : list of (bar_index, price, "H"|"L")  -- confirmed swings in order
      trend  : "UP" | "DOWN" | "FLAT"

    Algorithm:
      Walk bar by bar tracking last swing type.
      A new HIGH swing is confirmed when price retraces >= min_deviation% from peak.
      A new LOW  swing is confirmed when price rallies  >= min_deviation% from trough.
    """
    if len(highs) < 10:
        return [], "FLAT"

    swings: list[tuple[int, float, str]] = []
    last_type  = ""
    last_price = 0.0
    last_idx   = 0
    peak_price = float(highs[0])
    peak_idx   = 0
    trough_price = float(lows[0])
    trough_idx   = 0

    for i in range(1, len(highs)):
        h = float(highs[i])
        l = float(lows[i])

        if last_type == "" or last_type == "L":
            # Looking for next HIGH
            if h > peak_price:
                peak_price = h
                peak_idx   = i
            # Check if we retraced enough from peak → confirm peak as swing HIGH
            if peak_price > 0 and (peak_price - l) / peak_price * 100 >= min_deviation:
                if not swings or swings[-1][2] != "H" or peak_price > swings[-1][1]:
                    if swings and swings[-1][2] == "H":
                        swings[-1] = (peak_idx, peak_price, "H")
                    else:
                        swings.append((peak_idx, peak_price, "H"))
                last_type    = "H"
                trough_price = l
                trough_idx   = i

        if last_type == "" or last_type == "H":
            # Looking for next LOW
            if l < trough_price:
                trough_price = l
                trough_idx   = i
            # Check if we rallied enough from trough → confirm trough as swing LOW
            if trough_price > 0 and (h - trough_price) / trough_price * 100 >= min_deviation:
                if not swings or swings[-1][2] != "L" or trough_price < swings[-1][1]:
                    if swings and swings[-1][2] == "L":
                        swings[-1] = (trough_idx, trough_price, "L")
                    else:
                        swings.append((trough_idx, trough_price, "L"))
                last_type  = "L"
                peak_price = h
                peak_idx   = i

    # Determine trend from last 4 swings
    trend = "FLAT"
    if len(swings) >= 4:
        highs_zz = [p for _, p, t in swings[-4:] if t == "H"]
        lows_zz  = [p for _, p, t in swings[-4:] if t == "L"]
        if len(highs_zz) >= 2 and len(lows_zz) >= 2:
            if highs_zz[-1] > highs_zz[-2] and lows_zz[-1] > lows_zz[-2]:
                trend = "UP"    # HH + HL
            elif highs_zz[-1] < highs_zz[-2] and lows_zz[-1] < lows_zz[-2]:
                trend = "DOWN"  # LH + LL

    return swings, trend


def _last_swing(swings: list, kind: str) -> tuple[int, float] | None:
    """Last swing of given kind ("H" or "L")."""
    for idx, price, t in reversed(swings):
        if t == kind:
            return idx, price
    return None


# ═══════════════════════════════════════════════════════════════════════
# INDICATORS
# ═══════════════════════════════════════════════════════════════════════

def _atr(h, l, c, p):
    prev = np.roll(c, 1); prev[0] = c[0]
    tr   = np.maximum(h-l, np.maximum(np.abs(h-prev), np.abs(l-prev)))
    out  = np.zeros_like(tr)
    if len(tr) < p: return out
    out[p-1] = tr[:p].mean()
    for i in range(p, len(tr)):
        out[i] = (out[i-1]*(p-1) + tr[i]) / p
    return out


def _supertrend(h, l, c, period=10, mult=3.0):
    atr   = _atr(h, l, c, period)
    hl2   = (h + l) / 2.0
    upper = hl2 + mult * atr
    lower = hl2 - mult * atr
    st    = np.zeros_like(c); bull = np.ones(len(c), dtype=bool)
    st[0] = upper[0]
    for i in range(1, len(c)):
        fl = lower[i] if lower[i] > lower[i-1] or c[i-1] < st[i-1] else lower[i-1]
        fu = upper[i] if upper[i] < upper[i-1] or c[i-1] > st[i-1] else upper[i-1]
        bull[i] = True if c[i] > fu else (False if c[i] < fl else bull[i-1])
        st[i]   = fl if bull[i] else fu
    return st, bull


def _rsi(c, p=14):
    d  = np.diff(c, prepend=c[0])
    g  = np.where(d > 0, d, 0.0)
    ls = np.where(d < 0, -d, 0.0)
    ag = np.zeros_like(c); al = np.zeros_like(c)
    if len(c) <= p: return np.full_like(c, 50.0)
    ag[p] = g[1:p+1].mean(); al[p] = ls[1:p+1].mean()
    for i in range(p+1, len(c)):
        ag[i] = (ag[i-1]*(p-1) + g[i]) / p
        al[i] = (al[i-1]*(p-1) + ls[i]) / p
    rs = np.where(al > 0, ag / al, 100.0)
    return 100.0 - 100.0 / (1.0 + rs)


# ═══════════════════════════════════════════════════════════════════════
# SIGNAL GENERATION
# ═══════════════════════════════════════════════════════════════════════

def get_signal(
    ohlcv_5m:       dict,
    ohlcv_15m:      dict | None,
    ohlcv_1h:       dict | None,   # accepted but unused (kept for compat)
    symbol:         str,
    pivot_len:      int   = 3,     # unused (ZigZag replaces it)
    atr_period:     int   = 14,
    atr_mult:       float = 1.5,   # fallback SL mult if structure SL too close
    rr:             float = 2.5,
    min_vol_mult:   float = 0.8,
    st_period:      int   = 10,
    st_mult:        float = 3.0,
    adx_period:     int   = 14,    # unused
    adx_min:        float = 22.0,  # unused
    rsi_period:     int   = 14,
    min_atr_pct:    float = 0.12,
    min_score:      int   = 5,
    zz_deviation:   float = 0.5,   # ZigZag min % deviation
) -> tuple[Signal | None, str]:

    # ── Validate ──────────────────────────────────────────────────────
    if not ohlcv_5m:
        return None, "no_5m_data"

    h5, l5, c5, o5, v5 = (
        ohlcv_5m["high"], ohlcv_5m["low"], ohlcv_5m["close"],
        ohlcv_5m["open"], ohlcv_5m["volume"],
    )
    if len(c5) < 60:
        return None, f"bars_insuficientes_{len(c5)}"

    idx   = len(c5) - 2      # ultimo candle cerrado
    price = float(c5[idx])
    prev  = float(c5[idx-1])
    if price <= 0:
        return None, "precio_cero"

    # ── ATR filter ────────────────────────────────────────────────────
    atr_arr = _atr(h5, l5, c5, atr_period)
    atr_val = float(atr_arr[idx])
    if atr_val <= 0:
        return None, "atr_cero"
    if atr_val / price * 100 < min_atr_pct:
        return None, f"mercado_plano_{atr_val/price*100:.3f}pct"

    # ── Volume filter ─────────────────────────────────────────────────
    avg_vol   = float(np.mean(v5[-22:-2])) if len(v5) > 24 else 1.0
    vol_ratio = float(v5[idx]) / avg_vol if avg_vol > 0 else 0.0
    if vol_ratio < min_vol_mult:
        return None, f"volumen_bajo_{vol_ratio:.2f}x"

    # ── ZigZag on 5m ─────────────────────────────────────────────────
    # Use bars up to idx (exclude last unconfirmed candle)
    swings, zz_trend = compute_zigzag(h5[:idx], l5[:idx], zz_deviation)

    if len(swings) < 4:
        return None, f"pocos_swings_{len(swings)}"

    last_high = _last_swing(swings, "H")
    last_low  = _last_swing(swings, "L")

    if last_high is None or last_low is None:
        return None, "sin_swings_completos"

    zz_h_idx, zz_h_price = last_high
    zz_l_idx, zz_l_price = last_low

    # ── Breakout detection ────────────────────────────────────────────
    long_break  = prev <= zz_h_price and price > zz_h_price
    short_break = prev >= zz_l_price and price < zz_l_price

    if not long_break and not short_break:
        dist_h = abs(price - zz_h_price) / atr_val
        dist_l = abs(price - zz_l_price) / atr_val
        return None, f"sin_ruptura H={zz_h_price:.4f}({dist_h:.1f}R) L={zz_l_price:.4f}({dist_l:.1f}R)"

    # ── Trend alignment check ─────────────────────────────────────────
    if long_break  and zz_trend == "DOWN":
        return None, "long_en_tendencia_bajista"
    if short_break and zz_trend == "UP":
        return None, "short_en_tendencia_alcista"

    # ── Supertrend 15m ────────────────────────────────────────────────
    st_bull = None
    if ohlcv_15m and len(ohlcv_15m["close"]) > st_period + 3:
        _, st_b = _supertrend(
            ohlcv_15m["high"], ohlcv_15m["low"], ohlcv_15m["close"],
            st_period, st_mult,
        )
        st_bull = bool(st_b[-1])
    if st_bull is None:
        return None, "sin_supertrend_15m"
    if long_break  and not st_bull:
        return None, "long_bloqueado_ST_bajista"
    if short_break and st_bull:
        return None, "short_bloqueado_ST_alcista"

    # ── RSI momentum 5m ───────────────────────────────────────────────
    rsi_arr = _rsi(c5, rsi_period)
    rsi_val = float(rsi_arr[idx])
    if long_break  and rsi_val < 45:
        return None, f"long_RSI_debil={rsi_val:.1f}"
    if short_break and rsi_val > 55:
        return None, f"short_RSI_debil={rsi_val:.1f}"

    # ── Candle body quality (no dojis) ────────────────────────────────
    bar_range = float(h5[idx]) - float(l5[idx])
    body      = abs(price - float(o5[idx]))
    if bar_range > 0 and body / bar_range < 0.2:
        return None, f"doji_{body/bar_range:.2f}"

    # ── SL en estructura (swing anterior) ─────────────────────────────
    # LONG:  SL = ultimo swing LOW  (con buffer de 0.3 ATR)
    # SHORT: SL = ultimo swing HIGH (con buffer de 0.3 ATR)
    atr_buf = atr_val * 0.3

    if long_break:
        sl_struct = zz_l_price - atr_buf
        sl_dist   = price - sl_struct
        # Si el SL estructural queda demasiado lejos (> 3 ATR), usar ATR normal
        if sl_dist > atr_val * 3.0:
            sl_struct = price - atr_val * atr_mult
            sl_dist   = atr_val * atr_mult
        # Si queda demasiado cerca (< 0.5 ATR), expandir
        if sl_dist < atr_val * 0.5:
            sl_struct = price - atr_val * atr_mult
            sl_dist   = atr_val * atr_mult
    else:
        sl_struct = zz_h_price + atr_buf
        sl_dist   = sl_struct - price
        if sl_dist > atr_val * 3.0:
            sl_struct = price + atr_val * atr_mult
            sl_dist   = atr_val * atr_mult
        if sl_dist < atr_val * 0.5:
            sl_struct = price + atr_val * atr_mult
            sl_dist   = atr_val * atr_mult

    tp_dist = sl_dist * rr

    # ── Confluence score 0-10 ─────────────────────────────────────────
    score = 0
    score += 2                                        # ZigZag breakout
    score += 2                                        # Supertrend alineado
    score += 1 if zz_trend != "FLAT" else 0           # tendencia ZZ confirmada
    score += 1 if vol_ratio >= 1.5 else 0             # volumen spike
    score += 1 if (long_break and rsi_val > 55) or \
                  (short_break and rsi_val < 45) else 0  # RSI fuerte
    score += 1 if len(swings) >= 6 else 0             # estructura madura
    score += 1 if vol_ratio >= 2.5 else 0             # volumen extremo
    score += 1 if (long_break and zz_trend == "UP") or \
                  (short_break and zz_trend == "DOWN") else 0  # perfecta alineacion

    if score < min_score:
        return None, f"score_bajo={score}/{min_score}"

    if long_break:
        return Signal(
            symbol=symbol, side="BUY", price=price,
            sl=round(sl_struct, 8), tp=round(price + tp_dist, 8),
            atr_5m=atr_val, zz_high=zz_h_price, zz_low=zz_l_price,
            zz_trend=zz_trend, st_bull_15m=True,
            score=score, vol_ratio=round(vol_ratio, 2),
        ), "ok"

    return Signal(
        symbol=symbol, side="SELL", price=price,
        sl=round(sl_struct, 8), tp=round(price - tp_dist, 8),
        atr_5m=atr_val, zz_high=zz_h_price, zz_low=zz_l_price,
        zz_trend=zz_trend, st_bull_15m=False,
        score=score, vol_ratio=round(vol_ratio, 2),
    ), "ok"


# ═══════════════════════════════════════════════════════════════════════
# EXIT LOGIC
# ═══════════════════════════════════════════════════════════════════════

def check_trail_exit(
    ohlcv_5m:   dict,
    ohlcv_15m:  dict | None,
    trade_side: str,
    pivot_len:  int   = 3,     # unused, kept for compat
    st_period:  int   = 10,
    st_mult:    float = 3.0,
    rsi_period: int   = 14,
    zz_deviation: float = 0.5,
) -> str | None:
    """
    Exits (in priority order):
    1. Supertrend 5m flip  — exit en 1-3 velas
    2. ZigZag swing break contrario — estructura rota
    3. Supertrend 15m flip — confirmacion secundaria
    4. RSI divergencia
    """
    h5 = ohlcv_5m["high"]
    l5 = ohlcv_5m["low"]
    c5 = ohlcv_5m["close"]
    idx = len(c5) - 2

    # 1. ST 5m flip (mas rapido)
    if len(c5) > st_period + 3:
        _, st5b = _supertrend(h5, l5, c5, st_period, st_mult)
        if trade_side == "BUY"  and not st5b[-1]: return "ST5_FLIP"
        if trade_side == "SELL" and st5b[-1]:     return "ST5_FLIP"

    # 2. ZigZag swing break contrario
    if len(c5) > 30:
        swings, _ = compute_zigzag(h5[:idx], l5[:idx], zz_deviation)
        price = float(c5[idx])
        if trade_side == "BUY":
            lh = _last_swing(swings, "L")
            if lh and price < lh[1]:
                return "ZZ_SWING_BREAK"
        if trade_side == "SELL":
            lh = _last_swing(swings, "H")
            if lh and price > lh[1]:
                return "ZZ_SWING_BREAK"

    # 3. ST 15m flip
    if ohlcv_15m and len(ohlcv_15m["close"]) > st_period + 3:
        _, st15b = _supertrend(
            ohlcv_15m["high"], ohlcv_15m["low"], ohlcv_15m["close"],
            st_period, st_mult,
        )
        if trade_side == "BUY"  and not st15b[-1]: return "ST15_FLIP"
        if trade_side == "SELL" and st15b[-1]:     return "ST15_FLIP"

    # 4. RSI divergencia
    if len(c5) > rsi_period + 10:
        rsi = _rsi(c5, rsi_period)
        if trade_side == "BUY"  and c5[idx] > c5[idx-5] and rsi[idx] < rsi[idx-5] - 3:
            return "RSI_DIV"
        if trade_side == "SELL" and c5[idx] < c5[idx-5] and rsi[idx] > rsi[idx-5] + 3:
            return "RSI_DIV"

    return None
