import time
import schedule
import pandas as pd
from datetime import datetime

import config
from indicators import apply_quantum_edge
from bingx import get_klines, place_order, close_position, set_leverage
from telegram_notifier import (
    notify_startup,
    notify_shutdown,
    notify_error,
    notify_signal_long,
    notify_signal_short,
    notify_order_filled,
    notify_order_error,
    notify_close_timestop,
    notify_heartbeat,
)

# ─── Estado global del bot ───────────────────────────────────
state = {
    "in_position":  False,
    "direction":    "",        # "LONG" | "SHORT"
    "entry_price":  0.0,
    "sl_price":     0.0,
    "tp_price":     0.0,
    "qty":          0.0,
    "bars_in_trade": 0,
    "total_scans":  0,
    "total_signals": 0,
    "heartbeat_counter": 0,
}


# ─────────────────────────────────────────────────────────────
#  LÓGICA PRINCIPAL
# ─────────────────────────────────────────────────────────────

def bot_logic():
    global state
    now = datetime.now().strftime("%H:%M:%S")
    state["total_scans"] += 1
    state["heartbeat_counter"] += 1

    print(f"[{now}] 🔍 Escaneando {config.SYMBOL} — vela {config.TIMEFRAME}...")

    try:
        # ── 1. Obtener datos de mercado ──────────────────────
        raw_data = get_klines(config.SYMBOL, config.TIMEFRAME, limit=150)
        df = pd.DataFrame(raw_data)
        df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
        df = df[["open", "high", "low", "close", "volume"]].astype(float)

        # ── 2. Calcular indicadores V36 ──────────────────────
        df = apply_quantum_edge(df, pivot_len=config.PIVOT_LEN)
        current = df.iloc[-1]
        prev    = df.iloc[-2]

        # ── 3. Cruces de EMA ─────────────────────────────────
        cruz_alcista = (current["ema7"] > current["ema17"]) and (prev["ema7"] <= prev["ema17"])
        cruz_bajista = (current["ema7"] < current["ema17"]) and (prev["ema7"] >= prev["ema17"])

        # ── 4. Gestión de posición abierta ───────────────────
        if state["in_position"]:
            state["bars_in_trade"] += 1
            print(f"[{now}] 📂 En posición {state['direction']} — vela {state['bars_in_trade']}/{config.TIME_STOP}")

            if state["bars_in_trade"] >= config.TIME_STOP:
                print(f"[{now}] ⏳ TIME STOP — cerrando posición...")
                notify_close_timestop(state["direction"], state["bars_in_trade"])

                if not config.DRY_RUN:
                    close_side = "SELL" if state["direction"] == "LONG" else "BUY"
                    try:
                        close_position(config.SYMBOL, close_side, state["qty"])
                    except Exception as ex:
                        notify_error(f"Error al cerrar por time stop: {ex}")

                _reset_position()
            return  # No buscar nuevas entradas mientras se está en posición

        # ── 5. Gatillo LONG ──────────────────────────────────
        long_conditions = (
            cruz_alcista
            and (current["low"] < current["valley"])
            and bool(current["is_inst_vol"])
            and (current["adx"] > config.ADX_MIN)
            and (current["cvd"] > 0)
            and (current["close"] < current["vwap"])
        )

        # ── 6. Gatillo SHORT ─────────────────────────────────
        short_conditions = (
            cruz_bajista
            and (current["high"] > current["peak"])
            and bool(current["is_inst_vol"])
            and (current["adx"] > config.ADX_MIN)
            and (current["cvd"] < 0)
            and (current["close"] > current["vwap"])
        )

        # ── 7. Ejecutar LONG ─────────────────────────────────
        if long_conditions:
            state["total_signals"] += 1
            entry = round(float(current["close"]), 4)
            sl    = round(float(current["valley"]) - float(current["atr"]) * 0.8, 2)
            tp    = round(float(current["vwap"]), 2)
            qty   = round(config.TRADE_MARGIN / entry, 4)

            print(f"[{now}] 🟢 LONG  Entry={entry}  SL={sl}  TP={tp}  Qty={qty}")
            notify_signal_long(entry, sl, tp, qty,
                               adx=float(current["adx"]),
                               cvd=float(current["cvd"]))

            if not config.DRY_RUN:
                try:
                    resp = place_order(config.SYMBOL, "BUY", "MARKET", qty,
                                       stop_loss=sl, take_profit=tp)
                    order_id = resp.get("data", {}).get("order", {}).get("orderId", "N/A")
                    notify_order_filled("BUY", order_id, entry, qty)
                except Exception as ex:
                    notify_order_error("BUY", str(ex))
                    return

            state.update({
                "in_position":   True,
                "direction":     "LONG",
                "entry_price":   entry,
                "sl_price":      sl,
                "tp_price":      tp,
                "qty":           qty,
                "bars_in_trade": 0,
            })

        # ── 8. Ejecutar SHORT ────────────────────────────────
        elif short_conditions:
            state["total_signals"] += 1
            entry = round(float(current["close"]), 4)
            sl    = round(float(current["peak"]) + float(current["atr"]) * 0.8, 2)
            tp    = round(float(current["vwap"]), 2)
            qty   = round(config.TRADE_MARGIN / entry, 4)

            print(f"[{now}] 🔴 SHORT  Entry={entry}  SL={sl}  TP={tp}  Qty={qty}")
            notify_signal_short(entry, sl, tp, qty,
                                adx=float(current["adx"]),
                                cvd=float(current["cvd"]))

            if not config.DRY_RUN:
                try:
                    resp = place_order(config.SYMBOL, "SELL", "MARKET", qty,
                                       stop_loss=sl, take_profit=tp)
                    order_id = resp.get("data", {}).get("order", {}).get("orderId", "N/A")
                    notify_order_filled("SELL", order_id, entry, qty)
                except Exception as ex:
                    notify_order_error("SELL", str(ex))
                    return

            state.update({
                "in_position":   True,
                "direction":     "SHORT",
                "entry_price":   entry,
                "sl_price":      sl,
                "tp_price":      tp,
                "qty":           qty,
                "bars_in_trade": 0,
            })

        else:
            print(f"[{now}] 😴 Sin señal — ADX={round(float(current['adx']),1)}  CVD={round(float(current['cvd']),2)}")

    except Exception as e:
        print(f"[{now}] ❌ Error: {e}")
        notify_error(str(e))


def _reset_position():
    state.update({
        "in_position":   False,
        "direction":     "",
        "entry_price":   0.0,
        "sl_price":      0.0,
        "tp_price":      0.0,
        "qty":           0.0,
        "bars_in_trade": 0,
    })


def heartbeat_job():
    """Notificación de vida cada 20 ciclos (~1 hora en 3m)."""
    if state["heartbeat_counter"] >= 20:
        notify_heartbeat(
            scans=state["total_scans"],
            signals=state["total_signals"],
            in_position=state["in_position"],
            direction=state["direction"],
        )
        state["heartbeat_counter"] = 0


# ─────────────────────────────────────────────────────────────
#  ARRANQUE
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("  🤖 Sniper Bot V36 — Quantum Edge (BingX Edition)")
    print("=" * 50)
    print(f"  Modo: {'🟡 SIMULACIÓN' if config.DRY_RUN else '🔴 DINERO REAL'}")
    print(f"  Par:  {config.SYMBOL}   TF: {config.TIMEFRAME}")
    print("=" * 50)

    # Configurar apalancamiento al arrancar (solo modo real)
    if not config.DRY_RUN:
        try:
            set_leverage(config.SYMBOL, config.LEVERAGE)
            print(f"  ✅ Apalancamiento ×{config.LEVERAGE} configurado")
        except Exception as e:
            print(f"  ⚠️  No se pudo configurar apalancamiento: {e}")

    notify_startup()

    # Ejecución inmediata + scheduler cada 3 minutos
    bot_logic()
    schedule.every(3).minutes.at(":00").do(bot_logic)
    schedule.every(3).minutes.at(":00").do(heartbeat_job)

    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Bot detenido manualmente.")
        notify_shutdown("Interrupción manual (KeyboardInterrupt)")
    except Exception as fatal:
        print(f"\n💀 Error fatal: {fatal}")
        notify_shutdown(f"Error fatal: {fatal}")
        raise
