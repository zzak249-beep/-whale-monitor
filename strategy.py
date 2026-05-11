"""
strategy.py — V35 Golden Equilibrium
FIX: Ventana de crossover ampliada a 3 velas (antes era 1)
FIX: Diagnóstico detallado por símbolo
FIX: VOL_MULT default bajado a 0.9
"""
import logging
import numpy as np
import pandas as pd

from config import (
    EMA_FAST, EMA_MID, EMA_SLOW,
    PIVOT_LEN, VOL_MULT, ADX_MIN, ATR_SL_MULT,
)

logger = logging.getLogger(__name__)


# ─── Indicadores puros (numpy/pandas) ──────────────────────

def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()

def _atr(high, low, close, n=14) -> pd.Series:
    pc = close.shift(1)
    tr = pd.concat([high-low, (high-pc).abs(), (low-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(span=n, adjust=False).mean()

def _adx(high, low, close, n=14) -> pd.Series:
    pc = close.shift(1)
    tr = pd.concat([high-low, (high-pc).abs(), (low-pc).abs()], axis=1).max(axis=1)
    up   = high - high.shift(1)
    down = low.shift(1) - low
    pdm  = pd.Series(np.where((up>down)&(up>0), up, 0.0), index=high.index, dtype=float)
    mdm  = pd.Series(np.where((down>up)&(down>0), down, 0.0), index=high.index, dtype=float)
    atr_s = tr.ewm(span=n, adjust=False).mean()
    pdi   = 100 * pdm.ewm(span=n, adjust=False).mean() / atr_s.replace(0, np.nan)
    mdi   = 100 * mdm.ewm(span=n, adjust=False).mean() / atr_s.replace(0, np.nan)
    dx    = 100 * (pdi-mdi).abs() / (pdi+mdi).replace(0, np.nan)
    return dx.ewm(span=n, adjust=False).mean()

def _pivot_high(high: pd.Series, n: int) -> pd.Series:
    res = pd.Series(np.nan, index=high.index, dtype=float)
    arr = high.to_numpy()
    for i in range(n, len(arr)-n):
        w = arr[i-n:i+n+1]
        if arr[i] == w.max() and list(w).count(arr[i]) == 1:
            res.iloc[i] = arr[i]
    return res

def _pivot_low(low: pd.Series, n: int) -> pd.Series:
    res = pd.Series(np.nan, index=low.index, dtype=float)
    arr = low.to_numpy()
    for i in range(n, len(arr)-n):
        w = arr[i-n:i+n+1]
        if arr[i] == w.min() and list(w).count(arr[i]) == 1:
            res.iloc[i] = arr[i]
    return res


# ─── Estrategia V35 ────────────────────────────────────────

# Cuántas velas atrás buscar el crossover (Pine evalúa 1, ampliamos a 3)
CROSS_WINDOW = 3

class StrategyV35:

    def _add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["ema7"]        = _ema(df["close"], EMA_FAST)
        df["ema17"]       = _ema(df["close"], EMA_MID)
        df["ema21"]       = _ema(df["close"], EMA_SLOW)
        df["vol_ma"]      = _sma(df["volume"], 20)
        df["is_inst_vol"] = df["volume"] > (df["vol_ma"] * VOL_MULT)
        df["adx"]         = _adx(df["high"], df["low"], df["close"], 14)
        df["atr"]         = _atr(df["high"], df["low"], df["close"], 14)
        df["peak"]        = _pivot_high(df["high"], PIVOT_LEN).ffill()
        df["valley"]      = _pivot_low(df["low"],   PIVOT_LEN).ffill()
        return df

    def get_diagnostics(self, df: pd.DataFrame) -> dict:
        """
        Devuelve los valores actuales de todos los indicadores
        para un símbolo, sin importar si hay señal o no.
        Útil para ver por qué NO hay señal.
        """
        if len(df) < 30:
            return {"error": "pocas velas"}
        try:
            df = self._add_indicators(df)
            last = df.iloc[-1]
            prev = df.iloc[-2]
            vol_ratio = float(last["volume"]) / float(last["vol_ma"]) \
                        if float(last["vol_ma"]) > 0 else 0.0
            e7_now, e17_now = float(last["ema7"]), float(last["ema17"])
            e7_prv, e17_prv = float(prev["ema7"]), float(prev["ema17"])
            cross_up   = e7_prv <= e17_prv and e7_now > e17_now
            cross_down = e7_prv >= e17_prv and e7_now < e17_now
            gap_pct    = (e7_now - e17_now) / e17_now * 100
            return {
                "adx":        round(float(last["adx"]), 1),
                "vol_ratio":  round(vol_ratio, 2),
                "gap_ema_pct":round(gap_pct, 3),   # + = e7>e17, - = e7<e17
                "cross_up":   cross_up,
                "cross_down": cross_down,
                "vol_ok":     bool(last["is_inst_vol"]),
                "adx_ok":     float(last["adx"]) > ADX_MIN,
                "close":      round(float(last["close"]), 6),
                "valley":     round(float(last["valley"]), 6) if not pd.isna(last["valley"]) else None,
                "peak":       round(float(last["peak"]),   6) if not pd.isna(last["peak"])   else None,
            }
        except Exception as e:
            return {"error": str(e)}

    def get_signal(self, df: pd.DataFrame, adx_override: float = None) -> dict:
        """
        Señal V35. 
        FIX: Crossover buscado en las últimas CROSS_WINDOW velas (no solo la última).
        """
        NONE = {"signal": "NONE", "reason": ""}

        if len(df) < 62:
            return {**NONE, "reason": "pocas_velas"}

        df      = self._add_indicators(df)
        adx_min = adx_override if adx_override else ADX_MIN
        last    = df.iloc[-1]

        # ── Validar NaN ──────────────────────────────────────
        for col in ["ema7","ema17","ema21","adx","atr","peak","valley","vol_ma"]:
            if pd.isna(last[col]):
                return {**NONE, "reason": f"nan_{col}"}

        # ── Filtro Volumen ────────────────────────────────────
        vol_ratio = float(last["volume"]) / float(last["vol_ma"]) \
                    if float(last["vol_ma"]) > 0 else 0.0
        if vol_ratio < VOL_MULT:
            return {**NONE, "reason": f"vol_{vol_ratio:.2f}x<{VOL_MULT}"}

        # ── Filtro ADX ────────────────────────────────────────
        adx_val = float(last["adx"])
        if adx_val <= adx_min:
            return {**NONE, "reason": f"adx_{adx_val:.1f}<={adx_min}"}

        # ── Crossover en ventana de CROSS_WINDOW velas ────────
        # Una señal puede tardar hasta CROSS_WINDOW-1 velas en confirmarse
        window     = df.iloc[-(CROSS_WINDOW + 1):]
        e7_arr     = window["ema7"].to_numpy()
        e17_arr    = window["ema17"].to_numpy()
        cross_up_idx   = None
        cross_down_idx = None

        for i in range(1, len(e7_arr)):
            if e7_arr[i-1] <= e17_arr[i-1] and e7_arr[i] > e17_arr[i]:
                cross_up_idx = i
            elif e7_arr[i-1] >= e17_arr[i-1] and e7_arr[i] < e17_arr[i]:
                cross_down_idx = i

        has_cross_up   = cross_up_idx   is not None
        has_cross_down = cross_down_idx is not None

        if not has_cross_up and not has_cross_down:
            # Mostrar cuán lejos está el cruce
            gap = (float(last["ema7"]) - float(last["ema17"])) / float(last["ema17"]) * 100
            return {**NONE, "reason": f"no_cross gap={gap:.3f}%"}

        # ── Condición de estructura (Peak/Valley) ─────────────
        signal = "NONE"
        if has_cross_up   and float(last["low"])  < float(last["valley"]):
            signal = "LONG"
        elif has_cross_down and float(last["high"]) > float(last["peak"]):
            signal = "SHORT"
        else:
            if has_cross_up:
                reason = f"cross_up pero low({float(last['low']):.4f})>valley({float(last['valley']):.4f})"
            else:
                reason = f"cross_dn pero high({float(last['high']):.4f})<peak({float(last['peak']):.4f})"
            return {**NONE, "reason": reason}

        # ── SL / TP ──────────────────────────────────────────
        entry = float(last["close"])
        atr   = float(last["atr"])
        sl    = float(last["valley"]) - atr * ATR_SL_MULT if signal == "LONG" \
                else float(last["peak"]) + atr * ATR_SL_MULT
        tp    = float(last["ema21"])

        if signal == "LONG"  and (sl >= entry or tp <= entry):
            return {**NONE, "reason": f"geo_long entry={entry:.4f} sl={sl:.4f} tp={tp:.4f}"}
        if signal == "SHORT" and (sl <= entry or tp >= entry):
            return {**NONE, "reason": f"geo_short entry={entry:.4f} sl={sl:.4f} tp={tp:.4f}"}

        return {
            "signal":    signal,
            "reason":    "OK",
            "entry":     round(entry, 8),
            "sl":        round(sl, 8),
            "tp":        round(tp, 8),
            "atr":       round(atr, 8),
            "adx":       round(adx_val, 2),
            "strength":  self._strength(last),
            "peak":      round(float(last["peak"]),   8),
            "valley":    round(float(last["valley"]), 8),
            "vol_ratio": round(vol_ratio, 2),
        }

    @staticmethod
    def _strength(row) -> float:
        score = 0.0
        score += min(40.0, (float(row["adx"]) / 50.0) * 40.0)
        if float(row["vol_ma"]) > 0:
            score += min(30.0, (float(row["volume"]) / float(row["vol_ma"]) / 3.0) * 30.0)
        e7, e17, e21 = float(row["ema7"]), float(row["ema17"]), float(row["ema21"])
        if (e7 > e17 > e21) or (e7 < e17 < e21):
            score += 30.0
        elif e7 != e17:
            score += 15.0
        return round(score, 1)
