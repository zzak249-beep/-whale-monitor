"""
SAMA APEX Bot - Main Orchestrator
Loop principal: scan → signal → execute → manage → notify
"""
import asyncio
import logging
import sys
from datetime import datetime, timezone, date
from aiohttp import web

from config import (
    SYMBOLS, TF_LOCAL, TF_MACRO_1, TF_MACRO_2,
    LEVERAGE, SCAN_INTERVAL, HEALTH_PORT, CANDLES_NEEDED,
    FUNDING_FILTER, MAX_OPEN_TRADES
)
from bingx_client   import BingXClient
from indicators     import process_sama
from signal_engine  import SignalEngine
from risk_manager   import RiskManager
import telegram_notifier as tg

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("SAMA-APEX")


# ─── Health Server (Railway) ──────────────────────────────────────────────────

async def health_handler(request):
    return web.Response(text="OK", status=200)

async def start_health_server():
    app = web.Application()
    app.router.add_get("/",       health_handler)
    app.router.add_get("/health", health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", HEALTH_PORT)
    await site.start()
    logger.info(f"✅ Health server en puerto {HEALTH_PORT}")


# ─── Bot Core ─────────────────────────────────────────────────────────────────

class SamaApexBot:
    def __init__(self):
        self.signal_engine  = SignalEngine()
        self.risk_manager   = RiskManager()
        self.last_summary   = date.today()

    async def _fetch_tf_data(self, client: BingXClient, symbol: str, tf: str) -> dict | None:
        """Descarga velas y procesa SAMA para un timeframe"""
        df = await client.get_klines(symbol, tf, CANDLES_NEEDED)
        if df.empty or len(df) < 220:
            logger.warning(f"{symbol} {tf}: datos insuficientes ({len(df)} velas)")
            return None
        return process_sama(df)

    async def _scan_symbol(self, client: BingXClient, symbol: str) -> dict | None:
        """Evalúa un símbolo: descarga 3 TFs + funding → devuelve señal o None"""
        try:
            # Fetch paralelo de los 3 TFs
            local_data, m1_data, m2_data = await asyncio.gather(
                self._fetch_tf_data(client, symbol, TF_LOCAL),
                self._fetch_tf_data(client, symbol, TF_MACRO_1),
                self._fetch_tf_data(client, symbol, TF_MACRO_2),
            )

            if not all([local_data, m1_data, m2_data]):
                return None

            # Funding rate (edge especial)
            funding = 0.0
            if FUNDING_FILTER:
                funding = await client.get_funding_rate(symbol)

            return self.signal_engine.evaluate(symbol, local_data, m1_data, m2_data, funding)

        except Exception as e:
            logger.error(f"Error escaneando {symbol}: {e}")
            return None

    async def _execute_signal(self, client: BingXClient, signal: dict, balance: float):
        """Ejecuta la orden en BingX y registra la posición"""
        symbol    = signal["symbol"]
        direction = signal["direction"]
        entry     = signal["entry"]
        atr       = signal["atr"]
        conf      = signal["confluence"]
        score     = conf["score"]

        # ── SL desde ATR band del Pine Script ──────────────────────────────
        if direction == "LONG":
            sl = signal["lower_band"]   # lower_band = SAMA - ATR*mult
        else:
            sl = signal["upper_band"]   # upper_band = SAMA + ATR*mult

        # ── TP calculado por RiskManager ────────────────────────────────────
        tp = self.risk_manager.calculate_tp(entry, sl, direction, atr, score)

        # ── Verificar si se puede operar ────────────────────────────────────
        can, reason = self.risk_manager.can_open_trade(symbol, score, balance)
        if not can:
            logger.info(f"⏭️  {symbol} {direction} bloqueado: {reason}")
            return

        # ── Configurar apalancamiento ────────────────────────────────────────
        await client.set_leverage(symbol, LEVERAGE)

        # ── Calcular quantity ────────────────────────────────────────────────
        raw_qty = self.risk_manager.calculate_size(balance, entry, sl, score)
        qty     = await client.round_quantity(symbol, raw_qty)

        if qty <= 0:
            logger.warning(f"{symbol}: quantity calculada = {qty}, saltando")
            return

        # ── Colocar orden de entrada ─────────────────────────────────────────
        side          = "BUY"  if direction == "LONG"  else "SELL"
        position_side = "LONG" if direction == "LONG"  else "SHORT"

        order = await client.place_market_order(symbol, side, qty, position_side)
        if order.get("code") != 0:
            logger.error(f"Error abriendo {symbol}: {order}")
            await tg.notify_error(f"Orden fallida {symbol}: {order.get('msg', '')}")
            return

        # Usar precio de fill si está disponible, sino entry estimado
        fill_price = float(order.get("data", {}).get("avgPrice", entry) or entry)
        if fill_price <= 0:
            fill_price = entry

        # ── Colocar SL y TP ─────────────────────────────────────────────────
        sl_side = "SELL" if direction == "LONG" else "BUY"
        await asyncio.gather(
            client.place_tp_sl_order(symbol, sl_side, qty, sl, "STOP_MARKET", position_side),
            client.place_tp_sl_order(symbol, sl_side, qty, tp, "TAKE_PROFIT_MARKET", position_side),
        )

        # ── Registrar en RiskManager ─────────────────────────────────────────
        self.risk_manager.register_position(symbol, direction, fill_price, qty, sl, tp, atr, score)

        # ── Notificaciones ───────────────────────────────────────────────────
        await asyncio.gather(
            tg.notify_signal(symbol, signal, conf, fill_price, sl, tp, qty, balance),
            tg.notify_trade_opened(symbol, direction, fill_price, sl, tp, qty),
        )

        logger.info(f"🚀 {symbol} {direction} EJECUTADO | qty={qty} | entry={fill_price:.4f}")

    async def _manage_positions(self, client: BingXClient):
        """Gestión de posiciones abiertas: trailing stop + detección cierre"""
        for symbol, pos in list(self.risk_manager.open_positions.items()):
            try:
                # Precio actual
                ticker = await client.get_ticker(symbol)
                price  = float(ticker.get("lastPrice", 0))
                if price <= 0:
                    continue

                # Verificar si ya se cerró (TP/SL hit)
                bx_positions = await client.get_positions(symbol)
                still_open   = any(
                    p.get("positionSide") == pos.direction and float(p.get("positionAmt", 0)) != 0
                    for p in bx_positions
                )

                if not still_open:
                    result = self.risk_manager.close_position(symbol, price)
                    self.signal_engine.clear_direction(symbol)
                    if result:
                        await tg.notify_trade_closed(result)
                    continue

                # Trailing stop
                should_trail, new_sl = self.risk_manager.should_update_trailing(symbol, price)
                if should_trail:
                    old_sl = pos.trailing_sl
                    await client.update_trailing_stop(symbol, pos.direction, new_sl, pos.quantity)
                    await tg.notify_trailing_update(symbol, old_sl, new_sl)
                    logger.info(f"🔄 Trailing {symbol}: {old_sl:.4f} → {new_sl:.4f}")

            except Exception as e:
                logger.error(f"Error gestionando posición {symbol}: {e}")

    async def _daily_summary(self, balance: float):
        """Envía resumen diario a Telegram una vez al día"""
        today = date.today()
        if today != self.last_summary:
            self.last_summary = today
            stats = self.risk_manager.get_stats()
            await tg.notify_daily_summary(stats, balance)

    # ─── Main Loop ────────────────────────────────────────────────────────────

    async def run(self):
        logger.info("=" * 60)
        logger.info("  SAMA APEX BOT v1.0 — Arrancando")
        logger.info(f"  Pares: {', '.join(SYMBOLS)}")
        logger.info(f"  TFs: {TF_LOCAL} / {TF_MACRO_1} / {TF_MACRO_2}")
        logger.info("=" * 60)

        await tg.notify_startup(SYMBOLS, (TF_LOCAL, TF_MACRO_1, TF_MACRO_2))

        async with BingXClient() as client:
            # Balance inicial para circuit breaker
            balance = await client.get_balance()
            self.risk_manager.set_equity_start(balance)
            logger.info(f"💰 Balance inicial: {balance:.2f} USDT")

            while True:
                try:
                    loop_start = asyncio.get_event_loop().time()

                    # ── Actualizar balance ──────────────────────────────────
                    balance = await client.get_balance()
                    self.risk_manager.set_equity_start(balance)

                    # ── Circuit breaker check ───────────────────────────────
                    if self.risk_manager.is_circuit_broken(balance):
                        stats = self.risk_manager.get_stats()
                        if not stats["circuit"]:  # primera vez
                            await tg.notify_circuit_breaker(stats["daily_pnl"], balance)
                        await asyncio.sleep(SCAN_INTERVAL)
                        continue

                    # ── Gestionar posiciones abiertas ───────────────────────
                    await self._manage_positions(client)

                    # ── Scan de señales (solo si hay slots libres) ──────────
                    open_count = len(self.risk_manager.open_positions)
                    if open_count < MAX_OPEN_TRADES:
                        tasks   = [self._scan_symbol(client, sym) for sym in SYMBOLS]
                        results = await asyncio.gather(*tasks, return_exceptions=True)

                        # Ordenar señales por confluence score (mejor primero)
                        signals = [r for r in results if isinstance(r, dict) and r is not None]
                        signals.sort(key=lambda s: s["confluence"]["score"], reverse=True)

                        for signal in signals:
                            if len(self.risk_manager.open_positions) >= MAX_OPEN_TRADES:
                                break
                            await self._execute_signal(client, signal, balance)
                    else:
                        logger.info(f"📋 {open_count}/{MAX_OPEN_TRADES} slots ocupados — solo gestionando")

                    # ── Resumen diario ──────────────────────────────────────
                    await self._daily_summary(balance)

                    # ── Stats rápidas ───────────────────────────────────────
                    stats = self.risk_manager.get_stats()
                    logger.info(
                        f"💼 Balance: {balance:.2f} USDT | "
                        f"PnL día: {stats['daily_pnl']*100:+.2f}% | "
                        f"Trades: {stats['trades']} ({stats['wins']}W/{stats['losses']}L) | "
                        f"Pos: {stats['positions']}"
                    )

                    # ── Sleep hasta próximo scan ────────────────────────────
                    elapsed = asyncio.get_event_loop().time() - loop_start
                    sleep_t = max(1, SCAN_INTERVAL - elapsed)
                    logger.debug(f"⏱ Loop completado en {elapsed:.1f}s — esperando {sleep_t:.1f}s")
                    await asyncio.sleep(sleep_t)

                except KeyboardInterrupt:
                    logger.info("🛑 Bot detenido manualmente")
                    break
                except Exception as e:
                    logger.error(f"Error en loop principal: {e}", exc_info=True)
                    await tg.notify_error(str(e))
                    await asyncio.sleep(30)


# ─── Entry Point ──────────────────────────────────────────────────────────────

async def main():
    await start_health_server()
    bot = SamaApexBot()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
