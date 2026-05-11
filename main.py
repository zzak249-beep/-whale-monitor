"""
main.py — Cerebro del Sniper Bot V36 Quantum Edge.

Dos modos (BOT_MODE):
  MULTI  → Escanea TODOS los futuros de BingX cada ciclo,
            detecta señales, ejecuta las mejores oportunidades
            hasta MAX_OPEN_TRADES posiciones simultáneas.
  SINGLE → Opera solo el par definido en SYMBOL (comportamiento clásico).
"""
import time
import schedule
import pandas as pd
from datetime import datetime

import config
from indicators import apply_quantum_edge
from bingx import get_klines, place_order, close_position, set_leverage
from scanner import run_full_scan
from telegram_notifier import (
    notify_startup, notify_shutdown, notify_error,
    notify_scan_summary, notify_top_opportunities, notify_signals_found,
    notify_signal_long, notify_signal_short,
    notify_order_filled, notify_order_error,
    notify_close_timestop, notify_heartbeat,
)

# ─── Estado global ───────────────────────────────────────────
# open_positions: dict keyed by symbol
# {
#   "BTC-USDT": {direction, entry_price, sl_price, tp_price, qty, bars_in_trade}
# }
open_positions: dict = {}

stats = {
    "total_scans":   0,
    "total_signals": 0,
    "heartbeat_ctr": 0,
}


# ─────────────────────────────────────────────────────────────
#  MODO MULTI — escaneo de todos los pares
# ─────────────────────────────────────────────────────────────

def cycle_multi():
    """Ciclo completo en modo MULTI-MONEDA."""
    global open_positions
    now = datetime.now().strftime("%H:%M:%S")
    stats["total_scans"] += 1
    stats["heartbeat_ctr"] += 1

    # ── Gestionar posiciones abiertas ────────────────────────
    to_close = []
    for sym, pos in open_positions.items():
        pos["bars_in_trade"] += 1
        print(f"[{now}] 📂 {sym} {pos['direction']} — vela {pos['bars_in_trade']}/{config.TIME_STOP}")
        if pos["bars_in_trade"] >= config.TIME_STOP:
            to_close.append(sym)

    for sym in to_close:
        pos = open_positions[sym]
        print(f"[{now}] ⏳ TIME STOP {sym}")
        notify_close_timestop(sym, pos["direction"], pos["bars_in_trade"])
        if not config.DRY_RUN:
            close_side = "SELL" if pos["direction"] == "LONG" else "BUY"
            try:
                close_position(sym, close_side, pos["qty"])
            except Exception as ex:
                notify_error(f"Error cerrando {sym}: {ex}")
        del open_positions[sym]

    # ── Comprobar si hay hueco para nuevas posiciones ────────
    slots_free = config.MAX_OPEN_TRADES - len(open_positions)
    if slots_free <= 0:
        print(f"[{now}] 🔒 Máximo de posiciones alcanzado ({config.MAX_OPEN_TRADES}). Esperando...")
        return

    # ── Escaneo completo ─────────────────────────────────────
    t0 = time.time()
    try:
        scan = run_full_scan(
            timeframe=config.TIMEFRAME,
            min_volume=config.MIN_VOLUME_24H,
            top_n=config.TOP_N_RESULTS,
            delay_ms=config.SCAN_DELAY_MS,
        )
    except Exception as e:
        notify_error(f"Error en escaneo: {e}")
        return

    duration = time.time() - t0

    # ── Notificar resumen ────────────────────────────────────
    notify_scan_summary(scan["total"], scan["longs"], scan["shorts"], duration)
    notify_top_opportunities(scan["top"], top_n=config.TOP_N_RESULTS)

    # ── Filtrar señales que ya están en posición ─────────────
    new_signals = [
        r for r in scan["signals"]
        if r["symbol"] not in open_positions
    ][:slots_free]   # solo abrir hasta los slots disponibles

    if new_signals:
        stats["total_signals"] += len(new_signals)
        notify_signals_found(new_signals)

        for r in new_signals:
            _open_position(r)
    else:
        print(f"[{now}] 😴 Sin señales nuevas ejecutables.")


def _open_position(r: dict):
    """Abre una posición para un resultado del scanner."""
    sym    = r["symbol"]
    side   = "BUY" if r["signal"] == "LONG" else "SELL"
    entry  = r["price"]
    sl     = r["sl"]
    tp     = r["tp"]
    qty    = round(config.TRADE_MARGIN / entry, 4)
    direction = r["signal"]

    emoji = "🟢" if direction == "LONG" else "🔴"
    print(f"  {emoji} {direction} {sym}  Entry={entry}  SL={sl}  TP={tp}  Qty={qty}")

    if direction == "LONG":
        notify_signal_long(sym, entry, sl, tp, qty, adx=r["adx"], cvd=r["cvd"])
    else:
        notify_signal_short(sym, entry, sl, tp, qty, adx=r["adx"], cvd=r["cvd"])

    if not config.DRY_RUN:
        try:
            resp = place_order(sym, side, "MARKET", qty, stop_loss=sl, take_profit=tp)
            order_id = resp.get("data", {}).get("order", {}).get("orderId", "N/A")
            notify_order_filled(side, sym, order_id, entry, qty)
        except Exception as ex:
            notify_order_error(side, sym, str(ex))
            return

    open_positions[sym] = {
        "direction":     direction,
        "entry_price":   entry,
        "sl_price":      sl,
        "tp_price":      tp,
        "qty":           qty,
        "bars_in_trade": 0,
    }


# ─────────────────────────────────────────────────────────────
#  MODO SINGLE — un solo par
# ─────────────────────────────────────────────────────────────

def cycle_single():
    """Ciclo clásico de un único par (BOT_MODE=SINGLE)."""
    global open_positions
    sym = config.SYMBOL
    now = datetime.now().strftime("%H:%M:%S")
    stats["total_scans"] += 1
    stats["heartbeat_ctr"] += 1
    print(f"[{now}] 🔍 Escaneando {sym}...")

    try:
        raw = get_klines(sym, config.TIMEFRAME, limit=150)
        df  = pd.DataFrame(raw)
        df  = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
        df  = df[["open", "high", "low", "close", "volume"]].astype(float)
        df  = apply_quantum_edge(df, pivot_len=config.PIVOT_LEN)
        current = df.iloc[-1]
        prev    = df.iloc[-2]

        cruz_alcista = (current["ema7"] > current["ema17"]) and (prev["ema7"] <= prev["ema17"])
        cruz_bajista = (current["ema7"] < current["ema17"]) and (prev["ema7"] >= prev["ema17"])

        pos = open_positions.get(sym)

        # ── Gestionar posición abierta ───────────────────────
        if pos:
            pos["bars_in_trade"] += 1
            if pos["bars_in_trade"] >= config.TIME_STOP:
                notify_close_timestop(sym, pos["direction"], pos["bars_in_trade"])
                if not config.DRY_RUN:
                    close_side = "SELL" if pos["direction"] == "LONG" else "BUY"
                    try:
                        close_position(sym, close_side, pos["qty"])
                    except Exception as ex:
                        notify_error(f"Error cerrando {sym}: {ex}")
                del open_positions[sym]
            return

        entry  = round(float(current["close"]), 4)
        adx    = float(current["adx"])
        cvd    = float(current["cvd"])

        # ── Condiciones LONG ─────────────────────────────────
        if (cruz_alcista and float(current["low"]) < float(current["valley"])
                and bool(current["is_inst_vol"]) and adx > config.ADX_MIN
                and cvd > 0 and entry < float(current["vwap"])):
            sl  = round(float(current["valley"]) - float(current["atr"]) * 0.8, 2)
            tp  = round(float(current["vwap"]), 2)
            qty = round(config.TRADE_MARGIN / entry, 4)
            stats["total_signals"] += 1
            notify_signal_long(sym, entry, sl, tp, qty, adx, cvd)
            if not config.DRY_RUN:
                try:
                    resp = place_order(sym, "BUY", "MARKET", qty, stop_loss=sl, take_profit=tp)
                    oid = resp.get("data", {}).get("order", {}).get("orderId", "N/A")
                    notify_order_filled("BUY", sym, oid, entry, qty)
                except Exception as ex:
                    notify_order_error("BUY", sym, str(ex))
                    return
            open_positions[sym] = {"direction": "LONG", "entry_price": entry,
                                   "sl_price": sl, "tp_price": tp,
                                   "qty": qty, "bars_in_trade": 0}

        # ── Condiciones SHORT ────────────────────────────────
        elif (cruz_bajista and float(current["high"]) > float(current["peak"])
              and bool(current["is_inst_vol"]) and adx > config.ADX_MIN
              and cvd < 0 and entry > float(current["vwap"])):
            sl  = round(float(current["peak"]) + float(current["atr"]) * 0.8, 2)
            tp  = round(float(current["vwap"]), 2)
            qty = round(config.TRADE_MARGIN / entry, 4)
            stats["total_signals"] += 1
            notify_signal_short(sym, entry, sl, tp, qty, adx, cvd)
            if not config.DRY_RUN:
                try:
                    resp = place_order(sym, "SELL", "MARKET", qty, stop_loss=sl, take_profit=tp)
                    oid = resp.get("data", {}).get("order", {}).get("orderId", "N/A")
                    notify_order_filled("SELL", sym, oid, entry, qty)
                except Exception as ex:
                    notify_order_error("SELL", sym, str(ex))
                    return
            open_positions[sym] = {"direction": "SHORT", "entry_price": entry,
                                   "sl_price": sl, "tp_price": tp,
                                   "qty": qty, "bars_in_trade": 0}
        else:
            print(f"[{now}] 😴 Sin señal — ADX={round(adx,1)}  CVD={round(cvd,2)}")

    except Exception as e:
        print(f"[{now}] ❌ Error: {e}")
        notify_error(str(e))


# ─────────────────────────────────────────────────────────────
#  HEARTBEAT
# ─────────────────────────────────────────────────────────────

def heartbeat_check():
    threshold = 5 if config.BOT_MODE == "MULTI" else 20
    if stats["heartbeat_ctr"] >= threshold:
        notify_heartbeat(stats["total_scans"], stats["total_signals"], len(open_positions))
        stats["heartbeat_ctr"] = 0


# ─────────────────────────────────────────────────────────────
#  ARRANQUE
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("  🤖  Sniper Bot V36 — Quantum Edge (BingX Edition)")
    print("=" * 55)
    print(f"  Modo:    {'🌐 MULTI-MONEDA' if config.BOT_MODE == 'MULTI' else f'🎯 SINGLE ({config.SYMBOL})'}")
    print(f"  DRY RUN: {'🟡 SÍ (simulación)' if config.DRY_RUN else '🔴 NO (dinero real)'}")
    print(f"  TF:      {config.TIMEFRAME}   Margen: {config.TRADE_MARGIN} USDT   Lev: ×{config.LEVERAGE}")
    if config.BOT_MODE == "MULTI":
        print(f"  Vol min: ${config.MIN_VOLUME_24H:,.0f}   Top N: {config.TOP_N_RESULTS}   Max pos: {config.MAX_OPEN_TRADES}")
    print("=" * 55)

    if not config.DRY_RUN:
        try:
            sym_for_lev = config.SYMBOL if config.BOT_MODE == "SINGLE" else "BTC-USDT"
            set_leverage(sym_for_lev, config.LEVERAGE)
            print(f"  ✅ Apalancamiento ×{config.LEVERAGE} configurado")
        except Exception as e:
            print(f"  ⚠️  No se pudo configurar apalancamiento: {e}")

    notify_startup()

    cycle = cycle_multi if config.BOT_MODE == "MULTI" else cycle_single

    # Ejecución inmediata
    cycle()
    heartbeat_check()

    # Scheduler cada 3 minutos
    schedule.every(3).minutes.at(":00").do(cycle)
    schedule.every(3).minutes.at(":00").do(heartbeat_check)

    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Bot detenido manualmente.")
        notify_shutdown("Interrupción manual")
    except Exception as fatal:
        print(f"\n💀 Error fatal: {fatal}")
        notify_shutdown(f"Error fatal: {fatal}")
        raise
