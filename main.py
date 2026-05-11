"""
main.py — Sniper Bot V35: Golden Equilibrium
FIX: Diagnóstico completo por símbolo en cada tick
FIX: Logs de razón de rechazo por filtro
"""
import logging
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone

import schedule

from bingx_client import BingXClient
from config import (
    BINGX_MODE, CANDLE_INTERVAL, DATA_DIR, DRY_RUN,
    LEVERAGE, MAX_OPEN_TRADES, TIME_STOP_CANDLES, TOP_N_SYMBOLS,
    VOL_MULT, ADX_MIN,
)
from learning_engine import LearningEngine
from risk_manager import RiskManager
from hourly_reviewer import HourlyReviewer
from scanner import MarketScanner
from strategy import StrategyV35
from telegram_notifier import TelegramNotifier

# ─── Logging ──────────────────────────────────────────────
os.makedirs(DATA_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(f"{DATA_DIR}/bot.log"),
    ],
)
logger = logging.getLogger("SniperV35")


class SniperBotV35:
    def __init__(self):
        logger.info("Inicializando Sniper Bot V35: Golden Equilibrium...")
        self.client   = BingXClient()
        self.strategy = StrategyV35()
        self.telegram = TelegramNotifier()
        self.scanner  = MarketScanner(self.client)
        self.risk     = RiskManager()
        self.learning = LearningEngine(telegram=self.telegram)
        self.reviewer = HourlyReviewer(self.learning, self.telegram, self.client)
        self._active: dict  = {}
        self._top_symbols: list = []
        self._tick_count: int   = 0

    # ─── Startup ──────────────────────────────────────────
    def startup(self):
        balance = self.client.get_balance()
        self._top_symbols = self.scanner.get_top_symbols(TOP_N_SYMBOLS)
        logger.info(
            f"Balance=${balance:.2f} USDT | Pares={len(self._top_symbols)} | "
            f"DRY_RUN={DRY_RUN} | MODE={BINGX_MODE.upper()} | "
            f"VOL≥{VOL_MULT}x | ADX≥{ADX_MIN}"
        )
        self.telegram.notify_startup(balance, len(self._top_symbols), dry_run=DRY_RUN)
        self.telegram.notify_scan_results(self._top_symbols, self.scanner)

    # ─── Hourly ───────────────────────────────────────────
    def hourly_task(self):
        logger.info("Revisión horaria iniciada...")
        try:
            self.reviewer.run(self._active)
        except Exception as e:
            logger.error(f"Error revisión horaria: {e}", exc_info=True)
        self._top_symbols = self.scanner.get_top_symbols(TOP_N_SYMBOLS)
        logger.info(f"Re-escaneado. Top {len(self._top_symbols)} pares.")

    def daily_report(self):
        stats = self.learning.get_stats(today_only=True)
        self.telegram.notify_daily_report(stats)

    # ─── Tick principal ───────────────────────────────────
    def tick(self):
        self._tick_count += 1
        symbols  = [s["symbol"] for s in self._top_symbols]
        balance  = self.client.get_balance()
        reasons  = Counter()   # conteo de razones de rechazo
        checked  = 0
        best_sym = None        # símbolo más cercano a señal
        best_diag = {}

        for symbol in symbols:
            try:
                df = self.client.get_klines(symbol, CANDLE_INTERVAL, limit=150)
                if df.empty or len(df) < 62:
                    reasons["pocas_velas"] += 1
                    continue

                checked += 1

                if symbol in self._active:
                    self._manage_open(symbol, df)
                    continue

                # ── Diagnóstico + señal ──────────────────
                signal = self.strategy.get_signal(
                    df, adx_override=self.learning.params["adx_min"]
                )
                reason = signal.get("reason", "?")

                if signal["signal"] == "NONE":
                    reasons[reason.split("_")[0]] += 1  # agrupar por prefijo
                    # Guardar el más prometedor (adx alto + vol_ratio alto)
                    diag = self.strategy.get_diagnostics(df)
                    score = diag.get("adx", 0) + diag.get("vol_ratio", 0) * 10
                    if not best_sym or score > best_diag.get("_score", 0):
                        diag["_score"] = score
                        diag["_sym"]   = symbol
                        best_diag      = diag
                    continue

                # ── Señal detectada ──────────────────────
                logger.info(
                    f"[{symbol}] 🎯 SEÑAL {signal['signal']} | "
                    f"ADX={signal['adx']} vol={signal['vol_ratio']}x "
                    f"entry={signal['entry']} sl={signal['sl']} tp={signal['tp']}"
                )

                ok, lreason = self.learning.should_take(signal)
                if not ok:
                    logger.info(f"[{symbol}] Aprendizaje descarta: {lreason}")
                    reasons["aprendizaje"] += 1
                    continue

                result = self._open_trade(symbol, signal, balance)
                if result == "OPENED":
                    balance = self.client.get_balance()  # actualizar tras abrir

                time.sleep(0.3)

            except Exception as e:
                logger.error(f"[{symbol}] tick error: {e}", exc_info=False)

        # ─── Resumen del tick ────────────────────────────
        open_n = len(self._active)
        top_reasons = ", ".join(f"{k}={v}" for k, v in reasons.most_common(4))
        logger.info(
            f"TICK#{self._tick_count} | checked={checked} open={open_n}/{MAX_OPEN_TRADES} "
            f"bal=${balance:.2f} | rechazos: {top_reasons or 'ninguno'}"
        )

        # ─── Diagnóstico detallado cada 5 ticks ─────────
        if self._tick_count % 5 == 0 and best_diag:
            sym = best_diag.get("_sym", "?")
            logger.info(
                f"MEJOR_CANDIDATO {sym} | "
                f"ADX={best_diag.get('adx')} vol={best_diag.get('vol_ratio')}x "
                f"gap_ema={best_diag.get('gap_ema_pct')}% "
                f"vol_ok={best_diag.get('vol_ok')} adx_ok={best_diag.get('adx_ok')} "
                f"cross_up={best_diag.get('cross_up')} cross_dn={best_diag.get('cross_down')}"
            )

    # ─── Abrir trade ──────────────────────────────────────
    def _open_trade(self, symbol: str, signal: dict, balance: float) -> str:
        ok, reason = self.risk.can_open(symbol)
        if not ok:
            logger.info(f"[{symbol}] Risk block: {reason}")
            return "BLOCKED"

        qty = self.risk.calc_quantity(balance, signal["entry"], signal["sl"])
        if qty <= 0:
            logger.warning(f"[{symbol}] qty=0 — balance insuficiente")
            return "REJECTED"

        qty, ok, reason_qty = self.client.validate_qty(qty, signal["entry"])
        if not ok:
            logger.warning(f"[{symbol}] {reason_qty}")
            return "REJECTED"

        position_side = "LONG" if signal["signal"] == "LONG" else "SHORT"
        order_side    = "BUY"  if signal["signal"] == "LONG" else "SELL"

        result = self.client.place_order(
            symbol=symbol, side=order_side,
            position_side=position_side,
            quantity=qty, leverage=LEVERAGE,
        )

        if result.get("code") != 0:
            logger.error(f"[{symbol}] BingX rechazó la orden: {result}")
            return "REJECTED"

        # SL y TP
        close_side = "SELL" if signal["signal"] == "LONG" else "BUY"
        self.client.place_stop_order(
            symbol, close_side, position_side,
            stop_price=signal["sl"], quantity=qty, order_type="STOP_MARKET",
        )
        self.client.place_stop_order(
            symbol, close_side, position_side,
            stop_price=signal["tp"], quantity=qty, order_type="TAKE_PROFIT_MARKET",
        )

        meta = {
            "signal":        signal,
            "qty":           qty,
            "position_side": position_side,
            "open_time":     datetime.now(timezone.utc),
            "candle_count":  0,
            "position_usdt": qty * signal["entry"],
            "leverage":      LEVERAGE,
        }
        self._active[symbol] = meta
        self.risk.register(symbol, meta)
        self.telegram.notify_trade_open(symbol, signal, meta)
        logger.info(f"[{symbol}] ✅ TRADE ABIERTO {signal['signal']} qty={qty:.4f} entry={signal['entry']}")
        return "OPENED"

    # ─── Gestionar trade abierto ──────────────────────────
    def _manage_open(self, symbol: str, df):
        trade = self._active.get(symbol)
        if not trade:
            return

        trade["candle_count"] += 1
        current_price = float(df["close"].iloc[-1])
        signal        = trade["signal"]

        positions  = self.client.get_open_positions()
        still_open = any(
            p.get("symbol") == symbol and float(p.get("positionAmt", 0)) != 0
            for p in positions
        )

        if not still_open:
            self._close_trade(symbol, trade, current_price, "TP/SL")
            return

        if trade["candle_count"] >= TIME_STOP_CANDLES:
            logger.info(f"[{symbol}] ⏱️ TIME-STOP vela={trade['candle_count']}")
            self.client.cancel_all_orders(symbol)
            self.client.close_position(symbol, trade["position_side"], trade["qty"])
            self._close_trade(symbol, trade, current_price, "TIME_STOP")

    def _close_trade(self, symbol: str, trade: dict, price: float, reason: str):
        sig   = trade["signal"]
        pct   = (price - sig["entry"]) / sig["entry"]
        if sig["signal"] == "SHORT":
            pct = -pct
        pnl   = round(pct * trade["position_usdt"] * trade["leverage"], 4)
        dur   = (datetime.now(timezone.utc) - trade["open_time"]).total_seconds() / 60
        outcome = {"pnl": pnl, "reason": reason, "duration_min": dur}
        self.learning.record(symbol, sig, outcome)
        self.telegram.notify_trade_close(symbol, outcome)
        del self._active[symbol]
        self.risk.close(symbol)
        logger.info(f"[{symbol}] 🔒 CERRADO {reason} pnl={pnl:+.4f} dur={dur:.0f}min")

    # ─── Run ──────────────────────────────────────────────
    def run(self):
        self.startup()
        schedule.every(3).minutes.do(self.tick)
        schedule.every(1).hour.do(self.hourly_task)
        schedule.every().day.at("00:01").do(self.daily_report)
        logger.info("Scheduler activo | 3min tick | 1h review | 00:01 UTC report")
        self.tick()   # primera ejecución inmediata
        while True:
            schedule.run_pending()
            time.sleep(10)


if __name__ == "__main__":
    bot = SniperBotV35()
    bot.run()
