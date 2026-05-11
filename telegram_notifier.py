import requests
import config
from datetime import datetime

TELEGRAM_API = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}"


def _send(text: str, parse_mode: str = "HTML") -> bool:
    """Función base para enviar mensajes a Telegram."""
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
        print(f"[TELEGRAM] Error enviando mensaje: {e}")
        return False


# ─────────────────────────────────────────────────────────────
#  NOTIFICACIONES DE CICLO DE VIDA
# ─────────────────────────────────────────────────────────────

def notify_startup():
    mode = "🔴 DINERO REAL" if not config.DRY_RUN else "🟡 SIMULACIÓN (DRY RUN)"
    msg = (
        f"🤖 <b>Sniper Bot V36 — Quantum Edge</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Bot iniciado correctamente\n"
        f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n\n"
        f"📊 Par:       <code>{config.SYMBOL}</code>\n"
        f"⏱ Timeframe: <code>{config.TIMEFRAME}</code>\n"
        f"⚡ Apalancamiento: <code>×{config.LEVERAGE}</code>\n"
        f"💵 Margen/trade:   <code>{config.TRADE_MARGIN} USDT</code>\n\n"
        f"🎮 Modo: <b>{mode}</b>"
    )
    _send(msg)


def notify_shutdown(reason: str = "desconocido"):
    msg = (
        f"🛑 <b>Bot Detenido</b>\n"
        f"Razón: {reason}\n"
        f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    )
    _send(msg)


def notify_error(error: str):
    msg = (
        f"❌ <b>ERROR en el Bot</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<code>{error[:500]}</code>\n"
        f"⏰ {datetime.now().strftime('%H:%M:%S')}"
    )
    _send(msg)


# ─────────────────────────────────────────────────────────────
#  NOTIFICACIONES DE SEÑALES Y ÓRDENES
# ─────────────────────────────────────────────────────────────

def notify_signal_long(entry, sl, tp, qty, adx, cvd):
    mode_tag = "📋 SIMULADA" if config.DRY_RUN else "✅ EJECUTADA"
    rr = round(abs(tp - entry) / abs(entry - sl), 2) if abs(entry - sl) > 0 else "N/A"
    msg = (
        f"🟢 <b>SEÑAL LONG — {config.SYMBOL}</b>  {mode_tag}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 Entry:  <code>{entry}</code>\n"
        f"🛡 Stop Loss: <code>{sl}</code>\n"
        f"🎯 Take Profit: <code>{tp}</code>\n"
        f"📦 Cantidad: <code>{qty}</code>\n\n"
        f"📊 ADX:  <code>{round(adx, 1)}</code>\n"
        f"🌊 CVD:  <code>{round(cvd, 2)}</code>\n"
        f"⚖️ R/R:  <code>1:{rr}</code>\n"
        f"⏰ {datetime.now().strftime('%H:%M:%S')}"
    )
    _send(msg)


def notify_signal_short(entry, sl, tp, qty, adx, cvd):
    mode_tag = "📋 SIMULADA" if config.DRY_RUN else "✅ EJECUTADA"
    rr = round(abs(tp - entry) / abs(sl - entry), 2) if abs(sl - entry) > 0 else "N/A"
    msg = (
        f"🔴 <b>SEÑAL SHORT — {config.SYMBOL}</b>  {mode_tag}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📉 Entry:  <code>{entry}</code>\n"
        f"🛡 Stop Loss: <code>{sl}</code>\n"
        f"🎯 Take Profit: <code>{tp}</code>\n"
        f"📦 Cantidad: <code>{qty}</code>\n\n"
        f"📊 ADX:  <code>{round(adx, 1)}</code>\n"
        f"🌊 CVD:  <code>{round(cvd, 2)}</code>\n"
        f"⚖️ R/R:  <code>1:{rr}</code>\n"
        f"⏰ {datetime.now().strftime('%H:%M:%S')}"
    )
    _send(msg)


def notify_order_filled(side: str, order_id: str, fill_price: float, qty: float):
    emoji = "🟢" if side == "BUY" else "🔴"
    direction = "LONG" if side == "BUY" else "SHORT"
    msg = (
        f"{emoji} <b>ORDEN EJECUTADA — {direction}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 Order ID: <code>{order_id}</code>\n"
        f"💰 Precio de entrada: <code>{fill_price}</code>\n"
        f"📦 Cantidad: <code>{qty}</code>\n"
        f"⏰ {datetime.now().strftime('%H:%M:%S')}"
    )
    _send(msg)


def notify_order_error(side: str, error: str):
    msg = (
        f"⚠️ <b>ERROR AL COLOCAR ORDEN {side}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<code>{error[:400]}</code>\n"
        f"⏰ {datetime.now().strftime('%H:%M:%S')}"
    )
    _send(msg)


# ─────────────────────────────────────────────────────────────
#  NOTIFICACIONES DE CIERRE DE POSICIÓN
# ─────────────────────────────────────────────────────────────

def notify_close_timestop(direction: str, bars: int):
    msg = (
        f"⏳ <b>TIME STOP — Posición Cerrada</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Dirección: <b>{direction}</b>\n"
        f"⏱ {bars} velas alcanzadas ({bars * 3} min)\n"
        f"⏰ {datetime.now().strftime('%H:%M:%S')}"
    )
    _send(msg)


def notify_close_tp(direction: str, entry: float, tp: float):
    pnl_pct = round(abs(tp - entry) / entry * 100 * config.LEVERAGE, 2)
    msg = (
        f"🎯 <b>TAKE PROFIT ALCANZADO ✅</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Dirección: <b>{direction}</b>\n"
        f"📈 Entry: <code>{entry}</code> → TP: <code>{tp}</code>\n"
        f"💸 PnL est.: <b>+{pnl_pct}%</b>\n"
        f"⏰ {datetime.now().strftime('%H:%M:%S')}"
    )
    _send(msg)


def notify_close_sl(direction: str, entry: float, sl: float):
    pnl_pct = round(abs(sl - entry) / entry * 100 * config.LEVERAGE, 2)
    msg = (
        f"🛑 <b>STOP LOSS ACTIVADO</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Dirección: <b>{direction}</b>\n"
        f"📉 Entry: <code>{entry}</code> → SL: <code>{sl}</code>\n"
        f"💸 PnL est.: <b>-{pnl_pct}%</b>\n"
        f"⏰ {datetime.now().strftime('%H:%M:%S')}"
    )
    _send(msg)


# ─────────────────────────────────────────────────────────────
#  RESUMEN PERIÓDICO (cada hora)
# ─────────────────────────────────────────────────────────────

def notify_heartbeat(scans: int, signals: int, in_position: bool, direction: str = ""):
    pos_str = f"Sí — {direction}" if in_position else "No"
    msg = (
        f"💓 <b>Heartbeat — Bot Activo</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔍 Escaneos: <code>{scans}</code>\n"
        f"📡 Señales hoy: <code>{signals}</code>\n"
        f"📂 En posición: <code>{pos_str}</code>\n"
        f"⏰ {datetime.now().strftime('%d/%m %H:%M:%S')}"
    )
    _send(msg)
