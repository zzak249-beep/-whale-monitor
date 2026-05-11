import requests
import config
from datetime import datetime

TELEGRAM_API = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}"


def _send(text: str, parse_mode: str = "HTML") -> bool:
    if not config.TELEGRAM_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("[TELEGRAM] ⚠️  Token o Chat ID no configurados.")
        return False
    try:
        resp = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": config.TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"[TELEGRAM] Error: {e}")
        return False


def notify_startup():
    mode_str = "🔴 DINERO REAL" if not config.DRY_RUN else "🟡 SIMULACIÓN"
    bot_mode = "🌐 MULTI-MONEDA" if config.BOT_MODE == "MULTI" else f"🎯 SINGLE ({config.SYMBOL})"
    _send(
        f"🤖 <b>Sniper Bot V36 — Quantum Edge</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Bot iniciado  {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n\n"
        f"🗺 Modo:       <b>{bot_mode}</b>\n"
        f"⏱ Timeframe:  <code>{config.TIMEFRAME}</code>\n"
        f"⚡ Apalancamiento: <code>×{config.LEVERAGE}</code>\n"
        f"💵 Margen/trade:   <code>{config.TRADE_MARGIN} USDT</code>\n"
        f"📦 Max posiciones: <code>{config.MAX_OPEN_TRADES}</code>\n"
        f"💧 Vol mínimo 24h: <code>${config.MIN_VOLUME_24H:,.0f}</code>\n\n"
        f"🎮 Ejecución: <b>{mode_str}</b>"
    )


def notify_shutdown(reason: str = "desconocido"):
    _send(f"🛑 <b>Bot Detenido</b>\nRazón: {reason}\n⏰ {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")


def notify_error(error: str):
    _send(
        f"❌ <b>ERROR en el Bot</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<code>{error[:500]}</code>\n"
        f"⏰ {datetime.now().strftime('%H:%M:%S')}"
    )


def notify_scan_summary(total: int, longs: int, shorts: int, duration_s: float):
    _send(
        f"🔭 <b>Escaneo Completado</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔍 Pares analizados: <code>{total}</code>\n"
        f"🟢 Señales LONG:  <code>{longs}</code>\n"
        f"🔴 Señales SHORT: <code>{shorts}</code>\n"
        f"⏱ Duración: <code>{duration_s:.0f}s</code>\n"
        f"⏰ {datetime.now().strftime('%H:%M:%S')}"
    )


def notify_top_opportunities(results: list, top_n: int = 10):
    if not results:
        _send("📊 <b>Top Oportunidades</b>\n\nSin resultados destacados en este ciclo.")
        return

    lines = [
        f"📊 <b>Top {min(top_n, len(results))} Oportunidades — {config.TIMEFRAME}</b>",
        f"━━━━━━━━━━━━━━━━━━━━━━",
    ]
    for i, r in enumerate(results[:top_n], 1):
        sig_emoji = "🟢" if r["signal"] == "LONG" else ("🔴" if r["signal"] == "SHORT" else "⬜")
        rr_str = f"R/R {r['rr']}" if r["rr"] else "—"
        lines.append(
            f"{i}. {sig_emoji} <b>{r['symbol']}</b>  Score: <code>{r['score']}%</code>\n"
            f"   💰 {r['price']}  ADX: {r['adx']}  CVD: {r['cvd']}  {rr_str}"
        )
    lines.append(f"\n⏰ {datetime.now().strftime('%H:%M:%S')}")
    _send("\n".join(lines))


def notify_signals_found(signals: list):
    if not signals:
        return
    MAX_PER_MSG = 5
    for i in range(0, len(signals), MAX_PER_MSG):
        batch = signals[i:i + MAX_PER_MSG]
        lines = [f"🚨 <b>Señales Detectadas ({len(signals)} total)</b>", "━━━━━━━━━━━━━━━━━━━━━━"]
        for r in batch:
            emoji = "🟢 LONG" if r["signal"] == "LONG" else "🔴 SHORT"
            mode_tag = "📋 SIM" if config.DRY_RUN else "✅ REAL"
            rr_str = f"R/R <code>1:{r['rr']}</code>" if r["rr"] else ""
            lines.append(
                f"\n{emoji}  <b>{r['symbol']}</b>  {mode_tag}\n"
                f"  Entry: <code>{r['price']}</code>  SL: <code>{r['sl']}</code>  TP: <code>{r['tp']}</code>\n"
                f"  ADX: <code>{r['adx']}</code>  CVD: <code>{r['cvd']}</code>  Score: <code>{r['score']}%</code>  {rr_str}"
            )
        lines.append(f"\n⏰ {datetime.now().strftime('%H:%M:%S')}")
        _send("\n".join(lines))


def notify_signal_long(symbol, entry, sl, tp, qty, adx, cvd):
    mode_tag = "📋 SIMULADA" if config.DRY_RUN else "✅ EJECUTADA"
    rr = round(abs(tp - entry) / abs(entry - sl), 2) if abs(entry - sl) > 0 else "N/A"
    _send(
        f"🟢 <b>SEÑAL LONG — {symbol}</b>  {mode_tag}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 Entry: <code>{entry}</code>  SL: <code>{sl}</code>  TP: <code>{tp}</code>\n"
        f"📦 Qty: <code>{qty}</code>  ADX: <code>{round(adx,1)}</code>  CVD: <code>{round(cvd,2)}</code>  R/R: <code>1:{rr}</code>\n"
        f"⏰ {datetime.now().strftime('%H:%M:%S')}"
    )


def notify_signal_short(symbol, entry, sl, tp, qty, adx, cvd):
    mode_tag = "📋 SIMULADA" if config.DRY_RUN else "✅ EJECUTADA"
    rr = round(abs(tp - entry) / abs(sl - entry), 2) if abs(sl - entry) > 0 else "N/A"
    _send(
        f"🔴 <b>SEÑAL SHORT — {symbol}</b>  {mode_tag}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📉 Entry: <code>{entry}</code>  SL: <code>{sl}</code>  TP: <code>{tp}</code>\n"
        f"📦 Qty: <code>{qty}</code>  ADX: <code>{round(adx,1)}</code>  CVD: <code>{round(cvd,2)}</code>  R/R: <code>1:{rr}</code>\n"
        f"⏰ {datetime.now().strftime('%H:%M:%S')}"
    )


def notify_order_filled(side: str, symbol: str, order_id: str, fill_price: float, qty: float):
    emoji = "🟢" if side == "BUY" else "🔴"
    direction = "LONG" if side == "BUY" else "SHORT"
    _send(
        f"{emoji} <b>ORDEN EJECUTADA — {direction} {symbol}</b>\n"
        f"🆔 <code>{order_id}</code>  💰 <code>{fill_price}</code>  Qty: <code>{qty}</code>\n"
        f"⏰ {datetime.now().strftime('%H:%M:%S')}"
    )


def notify_order_error(side: str, symbol: str, error: str):
    _send(f"⚠️ <b>ERROR ORDEN {side} — {symbol}</b>\n<code>{error[:400]}</code>\n⏰ {datetime.now().strftime('%H:%M:%S')}")


def notify_close_timestop(symbol: str, direction: str, bars: int):
    _send(f"⏳ <b>TIME STOP — {symbol}</b>\nDirección: <b>{direction}</b>  |  {bars} velas ({bars * 3} min)\n⏰ {datetime.now().strftime('%H:%M:%S')}")


def notify_close_tp(symbol: str, direction: str, entry: float, tp: float):
    pnl = round(abs(tp - entry) / entry * 100 * config.LEVERAGE, 2)
    _send(f"🎯 <b>TAKE PROFIT ✅ — {symbol}</b>\nDirección: <b>{direction}</b>  Entry: <code>{entry}</code> → TP: <code>{tp}</code>\n💸 PnL est.: <b>+{pnl}%</b>\n⏰ {datetime.now().strftime('%H:%M:%S')}")


def notify_close_sl(symbol: str, direction: str, entry: float, sl: float):
    pnl = round(abs(sl - entry) / entry * 100 * config.LEVERAGE, 2)
    _send(f"🛑 <b>STOP LOSS — {symbol}</b>\nDirección: <b>{direction}</b>  Entry: <code>{entry}</code> → SL: <code>{sl}</code>\n💸 PnL est.: <b>-{pnl}%</b>\n⏰ {datetime.now().strftime('%H:%M:%S')}")


def notify_heartbeat(scans: int, signals: int, open_trades: int):
    _send(
        f"💓 <b>Heartbeat — Bot Activo</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔍 Ciclos: <code>{scans}</code>  📡 Señales: <code>{signals}</code>\n"
        f"📂 Posiciones: <code>{open_trades}/{config.MAX_OPEN_TRADES}</code>\n"
        f"⏰ {datetime.now().strftime('%d/%m %H:%M:%S')}"
    )
