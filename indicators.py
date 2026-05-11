import pandas as pd
import pandas_ta as ta
import numpy as np


def apply_quantum_edge(df: pd.DataFrame, pivot_len: int = 5) -> pd.DataFrame:
    """
    Aplica todos los indicadores del sistema V36 Quantum Edge.
    Retorna el DataFrame enriquecido con columnas adicionales.
    """
    # ─── Medias Móviles ───────────────────────────────────────
    df['ema7']  = ta.ema(df['close'], length=7)
    df['ema17'] = ta.ema(df['close'], length=17)
    df['ema21'] = ta.ema(df['close'], length=21)

    # ─── ADX & ATR ───────────────────────────────────────────
    adx_df    = ta.adx(df['high'], df['low'], df['close'], length=14)
    df['adx'] = adx_df['ADX_14']
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)

    # ─── Volumen Institucional ───────────────────────────────
    df['vol_ma']     = ta.sma(df['volume'], length=20)
    df['is_inst_vol'] = df['volume'] > (df['vol_ma'] * 1.5)

    # ─── Micro-CVD (Order Flow Proxy) ────────────────────────
    df['vol_bull'] = np.where(df['close'] > df['open'], df['volume'], 0.0)
    df['vol_bear'] = np.where(df['close'] < df['open'], df['volume'], 0.0)
    df['cvd']      = ta.sma(df['vol_bull'] - df['vol_bear'], length=5)

    # ─── Session VWAP ────────────────────────────────────────
    df['vwap'] = ta.vwap(df['high'], df['low'], df['close'], df['volume'])

    # ─── Zonas de Liquidez (sin repainting) ──────────────────
    window = 2 * pivot_len + 1
    df['rolling_max'] = df['high'].rolling(window=window).max()
    df['rolling_min'] = df['low'].rolling(window=window).min()

    df['is_peak']   = df['high'].shift(pivot_len) == df['rolling_max']
    df['is_valley'] = df['low'].shift(pivot_len)  == df['rolling_min']

    df['peak']   = df['high'].shift(pivot_len).where(df['is_peak']).ffill()
    df['valley'] = df['low'].shift(pivot_len).where(df['is_valley']).ffill()

    return df.dropna()
