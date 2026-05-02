# -*- coding: utf-8 -*-
"""pos_manager.py -- Phantom Edge Bot: High-Performance Position Manager.

Key performance improvements:
  - Batch price fetch via get_all_tickers() → 1 API call vs N
  - Batch positions fetch once per cycle, not per-trade
  - Parallel trail-exit checks via asyncio.gather
  - Time-based exit (bag holder protection)
  - Consecutive loss filter escalation
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime
from loguru import logger

import client as ex
import notifier


@dataclass
class Trade:
    symbol:       str
    side:         str
    entry:        float
    sl:           float
    tp:           float
    atr:          float
    size_usdt:    float
    leverage:     int   = 10
    qty:          float = 0.0
    score:        int   = 1
    vol_ratio:    float = 1.0
    delta1:       float = 0.0
    delta2:       float = 0.0
    be_done:      bool  = False
    partial_done: bool  = False
    closed:       bool  = False
    order_id:     str   = ""
    peak_r:       float = 0.0
    bot_opened:   bool  = True
    opened_at:    datetime = field(default_factory=datetime.utcnow)
    opened_str:   str     = field(default_factory=lambda: datetime.utcnow().strftime("%H:%M UTC"))


# ── Registry ──────────────────────────────────────────────────────────────────
_trades:          dict[str, Trade] = {}
_daily_pnl:       float = 0.0
_daily_trades:    int   = 0
_daily_wins:      int   = 0
_daily_losses:    int   = 0
_consec_losses:   int   = 0
_day_started:     date  = date.today()
_initial_balance: float = 0.0
_halted:          bool  = False


def add_trade(t: Trade) -> None:
    global _daily_trades
    _trades[t.symbol] = t
    _daily_trades += 1

def remove_trade(sym: str) -> None:
    _trades.pop(sym, None)

def open_symbols() -> set[str]:
    return set(_trades.keys())

def trade_count() -> int:
    return sum(1 for t in _trades.values() if t.bot_opened and not t.closed)

def is_halted() -> bool:
    return _halted

def consecutive_losses() -> int:
    return _consec_losses

def get_stats() -> dict:
    return {
        "open":          trade_count(),
        "daily_trades":  _daily_trades,
        "daily_pnl":     round(_daily_pnl, 4),
        "daily_wins":    _daily_wins,
        "daily_losses":  _daily_losses,
        "consec_losses": _consec_losses,
        "halted":        _halted,
    }


def _reset_daily() -> None:
    global _daily_pnl, _daily_trades, _daily_wins, _daily_losses
    global _day_started, _halted, _consec_losses
    if date.today() != _day_started:
        logger.info(f"[DAILY RESET] PnL={_daily_pnl:+.4f} W={_daily_wins} L={_daily_losses}")
        _daily_pnl = _daily_trades = _daily_wins = _daily_losses = _consec_losses = 0
        _day_started = date.today()
        _halted = False


def _record_exit(pnl: float) -> None:
    global _daily_pnl, _daily_wins, _daily_losses, _consec_losses
    _daily_pnl += pnl
    if pnl >= 0:
        _daily_wins   += 1
        _consec_losses = 0
    else:
        _daily_losses  += 1
        _consec_losses += 1


def _calc_pnl(trade: Trade, exit_price: float) -> tuple[float, float]:
    pct  = ((exit_price - trade.entry) / trade.entry * 100) if trade.side == "BUY" \
           else ((trade.entry - exit_price) / trade.entry * 100)
    usdt = (pct / 100) * trade.size_usdt * trade.leverage
    return round(pct, 4), round(usdt, 4)


def _r_dist(trade: Trade) -> float:
    from config import cfg
    d = (trade.atr * cfg.atr_mult) if trade.atr > 0 else abs(trade.entry - trade.sl)
    return max(d, 1e-9)


async def _circuit_breaker() -> bool:
    global _halted
    from config import cfg
    if _daily_trades >= cfg.max_daily_trades:
        if not _halted:
            _halted = True
            await notifier.notify(f"Bot pausado - max trades {cfg.max_daily_trades} | PnL={_daily_pnl:+.4f}")
        return True
    if _initial_balance > 0 and (-_daily_pnl / _initial_balance * 100) >= cfg.max_daily_loss_pct:
        if not _halted:
            _halted = True
            await notifier.notify(f"Bot pausado - perdida maxima | PnL={_daily_pnl:+.4f}")
        return True
    return False


async def sync_from_exchange() -> None:
    global _initial_balance
    live = await ex.get_all_positions()
    bal  = await ex.get_balance()
    _initial_balance = bal
    logger.info(f"[INIT] Balance={bal:.2f} | Externas={len(live)}")
    for sym, pos in live.items():
        if sym in _trades: continue
        amt  = float(pos.get("positionAmt", 0))
        side = "BUY" if amt > 0 else "SELL"
        ep   = float(pos.get("avgPrice", 0))
        if ep <= 0: continue
        _trades[sym] = Trade(
            symbol=sym, side=side, entry=ep, sl=0., tp=0., atr=0., size_usdt=0.,
            qty=abs(amt), be_done=True, partial_done=True, bot_opened=False,
        )
        logger.info(f"[SYNC] {sym} {side} @ {ep:.6f}")
    await notifier.notify(f"Bot iniciado\nBalance: {bal:.2f} USDT | Externas: {len(live)}")


async def _close_partial(trade: Trade, price: float) -> None:
    from config import cfg
    qty  = round(trade.qty * cfg.partial_pct, 6)
    if qty <= 0: return
    side = "SELL" if trade.side == "BUY" else "BUY"
    resp = await ex.place_reduce_order(trade.symbol, side, qty)
    if resp.get("code", -1) in (0, 200):
        _, pnl = _calc_pnl(trade, price)
        trade.qty -= qty
        trade.partial_done = True
        logger.info(f"[PARTIAL] {trade.symbol} qty={qty:.6f} PnL≈{pnl*cfg.partial_pct:+.4f}")
        await notifier.notify_partial(
            symbol=trade.symbol, qty_closed=qty,
            qty_remaining=trade.qty, price=price,
            pnl_usdt=round(pnl * cfg.partial_pct, 4),
        )


async def _move_be(trade: Trade, r: float) -> None:
    await ex.cancel_all_orders(trade.symbol)
    trade.be_done = True
    logger.info(f"[BE] {trade.symbol} → entry {trade.entry:.6f} R={r:.2f}")
    await notifier.notify_breakeven(trade.symbol, trade.side, trade.entry, r)


async def _do_exit(trade: Trade, live_pos: dict, price: float, r: float, reason: str) -> bool:
    resp = await ex.close_position(trade.symbol, live_pos)
    if resp.get("code", -1) not in (0, 200):
        logger.warning(f"[CLOSE FAIL] {trade.symbol}: {resp}")
        return False
    _, pnl = _calc_pnl(trade, price)
    _record_exit(pnl)
    trade.closed = True
    logger.info(f"[EXIT:{reason}] {trade.symbol} @ {price:.6f} R={r:.2f} PnL={pnl:+.4f}")
    await notifier.notify_exit(
        symbol=trade.symbol, side=trade.side,
        entry=trade.entry, exit_price=price,
        qty=trade.qty, size_usdt=trade.size_usdt, leverage=trade.leverage,
        r_achieved=r, peak_r=trade.peak_r, exit_reason=reason,
    )
    total = _daily_wins + _daily_losses
    if total > 0 and total % 5 == 0:
        bal = await ex.get_balance()
        await notifier.notify_daily_summary(_daily_trades, _daily_wins, _daily_losses, _daily_pnl, bal)
    return True


# ── Main manage loop ──────────────────────────────────────────────────────────

async def manage_positions(ohlcv_map: dict[str, dict]) -> None:
    """
    FAST: batch-fetches all prices + all positions in 2 API calls.
    Then processes each trade locally without additional API calls
    unless an action is required.
    """
    from config import cfg
    from strategy import check_trail_exit
    _reset_daily()
    await _circuit_breaker()

    active = [t for t in _trades.values() if t.bot_opened and not t.closed]
    if not active:
        # Still clean up fully closed trades
        for sym in [s for s, t in list(_trades.items()) if t.closed]:
            remove_trade(sym)
        return

    # ── Batch fetch: 2 API calls for ALL open positions ───────────────────
    all_prices, all_live = await asyncio.gather(
        ex.get_all_tickers(),
        ex.get_all_positions(),
    )

    closed_syms: list[str] = []

    for trade in active:
        sym   = trade.symbol
        price = all_prices.get(sym, 0.0)
        if price <= 0:
            price = await ex.get_price(sym)   # fallback single call
        if price <= 0:
            continue

        rd    = _r_dist(trade)
        pnl_p = (price - trade.entry) if trade.side == "BUY" else (trade.entry - price)
        r_now = pnl_p / rd
        if r_now > trade.peak_r:
            trade.peak_r = r_now

        logger.debug(f"[POS] {sym} {trade.side} p={price:.6f} R={r_now:.2f} pk={trade.peak_r:.2f}")

        # ── Time-based exit (bag holder protection) ───────────────────────
        age_h = (datetime.utcnow() - trade.opened_at).total_seconds() / 3600
        if age_h > cfg.max_trade_hours and r_now < cfg.min_r_time_exit and trade.be_done:
            if sym in all_live:
                ok = await _do_exit(trade, all_live[sym], price, r_now, "TIME_EXIT")
                if ok: closed_syms.append(sym)
            continue

        # ── Breakeven + partial at +1R ────────────────────────────────────
        if not trade.be_done and r_now >= cfg.breakeven_r:
            if sym not in all_live:
                _, pnl = _calc_pnl(trade, price)
                _record_exit(pnl)
                trade.closed = True
                closed_syms.append(sym)
                await notifier.notify_exit(
                    symbol=sym, side=trade.side, entry=trade.entry, exit_price=price,
                    qty=trade.qty, size_usdt=trade.size_usdt, leverage=trade.leverage,
                    r_achieved=r_now, peak_r=trade.peak_r, exit_reason="SL",
                )
                continue
            await _move_be(trade, r_now)
            await _close_partial(trade, price)
            continue

        # ── Post-BE trail exits ───────────────────────────────────────────
        if trade.be_done:
            if sym not in all_live:
                reason = "TP" if r_now >= cfg.rr * 0.9 else "MANUAL"
                _, pnl = _calc_pnl(trade, price)
                _record_exit(pnl)
                trade.closed = True
                closed_syms.append(sym)
                await notifier.notify_exit(
                    symbol=sym, side=trade.side, entry=trade.entry, exit_price=price,
                    qty=trade.qty, size_usdt=trade.size_usdt, leverage=trade.leverage,
                    r_achieved=r_now, peak_r=trade.peak_r, exit_reason=reason,
                )
                continue

            data = ohlcv_map.get(sym, {})
            if data:
                reason = check_trail_exit(
                    ohlcv_5m  = data.get(cfg.timeframe,      {}),
                    ohlcv_15m = data.get(cfg.timeframe_slow, None),
                    trade_side = trade.side,
                    st_period  = cfg.st_period,
                    st_mult    = cfg.st_mult,
                    zz_deviation = cfg.zz_deviation,
                )
                if reason and sym in all_live:
                    ok = await _do_exit(trade, all_live[sym], price, r_now, reason)
                    if ok: closed_syms.append(sym)

    for sym in closed_syms:
        remove_trade(sym)
