"""
SAMA APEX Bot - Signal Engine
Genera señales de entrada validadas con el sistema SAMA multi-TF.
Incluye state tracking para evitar señales duplicadas (replica Pine Script sig var).
"""
import logging
from dataclasses import dataclass, field
from typing import Optional
from indicators import confluence_score, is_active_session
from config import TF_LOCAL, TF_MACRO_1, TF_MACRO_2, MIN_CONFLUENCE

logger = logging.getLogger(__name__)


@dataclass
class SignalState:
    """Estado de señal por símbolo (replica la var sig de Pine Script)"""
    sig:       int = 0         # -1 SHORT, 0 NEUTRAL, 1 LONG
    last_dir:  str = "NONE"    # Última dirección ejecutada
    count:     int = 0         # Total señales generadas


class SignalEngine:
    def __init__(self):
        self._states: dict[str, SignalState] = {}

    def _get_state(self, symbol: str) -> SignalState:
        if symbol not in self._states:
            self._states[symbol] = SignalState()
        return self._states[symbol]

    def reset_state(self, symbol: str):
        """Resetea estado tras cerrar posición"""
        self._states[symbol] = SignalState()

    def evaluate(
        self,
        symbol:    str,
        local:     dict,
        m1:        dict,
        m2:        dict,
        funding:   float = 0.0,
    ) -> Optional[dict]:
        """
        Evalúa si hay señal nueva para el símbolo.
        Retorna dict con señal completa o None si no hay señal.

        Lógica exacta del Pine Script:
          buy  = all BULL + not(all BULL prev) + has_volume
          sell = all BEAR + not(all BEAR prev) + has_volume
          var sig: solo cambia de 0→1 o 0→-1, evita repetición
        """
        state   = self._get_state(symbol)
        session = is_active_session()

        lt  = local["trend"]
        m1t = m1["trend"]
        m2t = m2["trend"]

        # Condición de volumen (cualquiera de los TF debe tenerlo)
        has_volume = local["has_volume"] or m1["has_volume"]

        # ── BUY condition ───────────────────────────────────────────────
        all_bull      = (lt == "BULL" and m1t == "BULL" and m2t == "BULL")
        prev_all_bull = (local["prev_trend"] == "BULL")
        buy  = all_bull and not prev_all_bull and has_volume

        # ── SELL condition ──────────────────────────────────────────────
        all_bear      = (lt == "BEAR" and m1t == "BEAR" and m2t == "BEAR")
        prev_all_bear = (local["prev_trend"] == "BEAR")
        sell = all_bear and not prev_all_bear and has_volume

        # ── State machine (replica var sig de Pine Script) ──────────────
        if buy and state.sig <= 0:
            state.sig = 1
        elif sell and state.sig >= 0:
            state.sig = -1

        long_signal  = (state.sig == 1)  and (state.last_dir != "LONG")
        short_signal = (state.sig == -1) and (state.last_dir != "SHORT")

        if not long_signal and not short_signal:
            return None

        # ── Confluence scoring ──────────────────────────────────────────
        conf = confluence_score(local, m1, m2, funding, session)

        if conf["score"] < MIN_CONFLUENCE:
            logger.debug(f"{symbol}: señal pero confluence {conf['score']} < {MIN_CONFLUENCE}, descartada")
            return None

        direction = "LONG" if long_signal else "SHORT"

        # Actualizar estado para no repetir señal
        state.last_dir = direction
        state.count   += 1

        logger.info(
            f"📡 SEÑAL {symbol} {direction} | score={conf['score']} | "
            f"slopes: {local['slope']:.1f}° {m1['slope']:.1f}° {m2['slope']:.1f}°"
        )

        return {
            "symbol":    symbol,
            "direction": direction,
            "local":     local,
            "m1":        m1,
            "m2":        m2,
            "confluence": conf,
            # Niveles de precio para TP/SL
            "entry":     local["close"],
            "upper_band": local["upper_band"],
            "lower_band": local["lower_band"],
            "atr":       local["atr"],
        }

    def clear_direction(self, symbol: str):
        """Llamar al cerrar posición para que el bot pueda tomar nuevas señales"""
        state = self._get_state(symbol)
        state.last_dir = "NONE"
        state.sig      = 0
