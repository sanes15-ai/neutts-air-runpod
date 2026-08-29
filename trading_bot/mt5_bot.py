"""Live trading loop against a MetaTrader 5 terminal.

Runs the validated strategy trio on a **demo** account. Three hard safety
properties, checked before any order is sent:

1. The account must be flagged DEMO by the terminal itself, unless the operator
   has explicitly passed --i-understand-live. There is no accidental path to
   real money.
2. Equity floor and daily-loss limits halt trading rather than "trying to win
   it back", which is how accounts die.
3. Every order carries a stop loss computed from ATR *before* the order is
   sent. No position is ever opened without a predefined exit.

The MetaTrader5 package is Windows-only and talks to a terminal running on the
same machine, so this module imports it lazily: the rest of the package stays
importable (and testable) on any platform.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd

from . import strategies as S
from .indicators import atr

log = logging.getLogger("trading_bot.mt5")

#: Validated strategy sets, per market. These differ because the markets differ:
#: FX ranges and mean-reverts, so reversion strategies win there; crypto trends
#: hard, so breakout strategies win. Using the FX set on BTC (or vice versa)
#: throws away most of the edge.
STRATEGY_SETS = {
    # Out-of-sample on BTC: Sharpe 1.29, and positive through both the 2018 and
    # 2022 bear markets because it takes short positions rather than only long.
    "crypto": ["keltner_breakout", "adx_filtered_ema", "new_high_20"],
    # Out-of-sample on EURUSD: Sharpe 1.23. Two mean-reversion strategies that
    # are negatively correlated with the momentum one.
    "fx": ["keltner_revert", "rsi7_revert_25_75", "roc_momentum_20"],
}

DEFAULT_STRATEGIES = STRATEGY_SETS["crypto"]


def strategies_for(symbol: str) -> list[str]:
    """Pick the validated strategy set matching the instrument's character."""
    upper = symbol.upper()
    is_crypto = any(token in upper for token in ("BTC", "ETH", "XRP", "SOL", "LTC", "DOGE"))
    return list(STRATEGY_SETS["crypto" if is_crypto else "fx"])


class SafetyError(RuntimeError):
    """Raised when a safety precondition fails. Never caught internally."""


@dataclass
class BotConfig:
    symbol: str = "EURUSD"
    timeframe: str = "D1"
    strategies: tuple[str, ...] = ()   # empty -> chosen by symbol in __post_init__
    #: Fraction of equity risked per trade, per strategy. 0.10 was the
    #: aggressive-but-survivable setting in backtest (~15% max drawdown).
    risk_per_trade: float = 0.10
    stop_atr_mult: float = 2.0
    target_atr_mult: float = 3.0
    atr_period: int = 14
    #: Halt if equity falls below this fraction of the starting balance.
    equity_floor: float = 0.60
    #: Halt for the day after losing this fraction of the day's opening equity.
    daily_loss_limit: float = 0.15
    max_open_positions: int = 3
    bars_to_fetch: int = 500
    poll_seconds: float = 60.0
    magic: int = 20260829
    allow_live: bool = False
    log_path: str = "mt5_trades.jsonl"

    def __post_init__(self) -> None:
        if not self.strategies:
            self.strategies = tuple(strategies_for(self.symbol))


@dataclass
class BotState:
    start_equity: float = 0.0
    day_start_equity: float = 0.0
    day: str = ""
    halted: bool = False
    halt_reason: str = ""
    orders_sent: int = 0
    history: list = field(default_factory=list)


def _mt5():
    """Import the MetaTrader5 package, with a clear message if unavailable."""
    try:
        import MetaTrader5  # type: ignore[import-not-found]
    except ImportError as exc:
        raise SafetyError(
            "MetaTrader5 package not available. It is Windows-only and requires the "
            "MT5 terminal installed on the same machine: pip install MetaTrader5"
        ) from exc
    return MetaTrader5


TIMEFRAMES = {"M5": 5, "M15": 15, "M30": 30, "H1": 16385, "H4": 16388, "D1": 16408}


def connect(config: BotConfig):
    """Initialise the terminal link and verify the account is safe to trade."""
    mt5 = _mt5()
    if not mt5.initialize():
        raise SafetyError(f"MT5 initialize() failed: {mt5.last_error()}")
    info = mt5.account_info()
    if info is None:
        raise SafetyError(f"could not read account info: {mt5.last_error()}")

    is_demo = info.trade_mode == getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0)
    if not is_demo and not config.allow_live:
        mt5.shutdown()
        raise SafetyError(
            f"account {info.login} is NOT a demo account (trade_mode={info.trade_mode}). "
            "Refusing to trade. Pass allow_live=True only if you truly intend real money."
        )
    if not info.trade_allowed:
        log.warning("terminal reports trading is not allowed (check 'Algo Trading' button)")

    log.info(
        "connected: login=%s server=%s %s balance=%.2f %s",
        info.login, info.server, "DEMO" if is_demo else "*** LIVE ***",
        info.balance, info.currency,
    )
    return mt5, info


def fetch_bars(mt5, config: BotConfig) -> pd.DataFrame:
    """Pull recent completed bars as an OHLC frame."""
    tf = TIMEFRAMES.get(config.timeframe)
    if tf is None:
        raise SafetyError(f"unknown timeframe {config.timeframe!r}; known: {sorted(TIMEFRAMES)}")
    rates = mt5.copy_rates_from_pos(config.symbol, tf, 0, config.bars_to_fetch)
    if rates is None or len(rates) < 100:
        raise SafetyError(f"insufficient bars for {config.symbol}: {mt5.last_error()}")
    frame = pd.DataFrame(rates)
    frame["time"] = pd.to_datetime(frame["time"], unit="s", utc=True)
    # The final bar is still forming. Trading on it means acting on a close
    # that has not happened -- the live equivalent of lookahead.
    return frame[["time", "open", "high", "low", "close"]].iloc[:-1].reset_index(drop=True)


def desired_position(df: pd.DataFrame, names: tuple[str, ...]) -> tuple[int, dict]:
    """Combine strategy votes into one position.

    Each strategy votes -1/0/+1 on the last completed bar; the net sign is the
    target. Requiring agreement means conflicting strategies cancel out rather
    than both taking opposing positions and paying spread twice.
    """
    votes = {}
    total = 0
    for name in names:
        strategy = S.REGISTRY.get(name)
        if strategy is None:
            raise SafetyError(f"unknown strategy {name!r}")
        vote = int(strategy.signal(df).iloc[-1])
        votes[name] = vote
        total += vote
    return (1 if total > 0 else -1 if total < 0 else 0), votes


def check_safety(mt5, config: BotConfig, state: BotState) -> None:
    """Halt the bot if any risk limit has been breached."""
    info = mt5.account_info()
    if info is None:
        raise SafetyError("lost account connection")
    equity = info.equity

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if today != state.day:
        state.day, state.day_start_equity = today, equity

    if equity < state.start_equity * config.equity_floor:
        state.halted = True
        state.halt_reason = (
            f"equity {equity:.2f} below floor "
            f"({config.equity_floor:.0%} of {state.start_equity:.2f})"
        )
    elif equity < state.day_start_equity * (1 - config.daily_loss_limit):
        state.halted = True
        state.halt_reason = (
            f"daily loss limit hit: {equity:.2f} vs day open {state.day_start_equity:.2f}"
        )
    if state.halted:
        raise SafetyError(state.halt_reason)


def position_size(mt5, config: BotConfig, equity: float, stop_distance: float) -> float:
    """Volume in lots, sized so a stop-out costs `risk_per_trade` of equity."""
    spec = mt5.symbol_info(config.symbol)
    if spec is None:
        raise SafetyError(f"unknown symbol {config.symbol}")
    tick_value, tick_size = spec.trade_tick_value, spec.trade_tick_size
    if tick_value <= 0 or tick_size <= 0 or stop_distance <= 0:
        return 0.0
    # Loss per lot if the stop is hit, in account currency.
    loss_per_lot = (stop_distance / tick_size) * tick_value
    if loss_per_lot <= 0:
        return 0.0
    volume = (equity * config.risk_per_trade) / loss_per_lot
    # Respect the broker's lot granularity and bounds.
    step = spec.volume_step or 0.01
    volume = max(spec.volume_min, min(spec.volume_max, round(volume / step) * step))
    return round(volume, 2)


def open_positions(mt5, config: BotConfig) -> list:
    positions = mt5.positions_get(symbol=config.symbol)
    return [p for p in (positions or []) if p.magic == config.magic]


def send_order(mt5, config: BotConfig, direction: int, volume: float,
               stop: float, target: float) -> dict:
    """Place a market order with stop loss and take profit attached."""
    tick = mt5.symbol_info_tick(config.symbol)
    if tick is None:
        raise SafetyError(f"no tick for {config.symbol}")
    price = tick.ask if direction > 0 else tick.bid
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": config.symbol,
        "volume": volume,
        "type": mt5.ORDER_TYPE_BUY if direction > 0 else mt5.ORDER_TYPE_SELL,
        "price": price,
        "sl": stop,
        "tp": target,
        "deviation": 20,
        "magic": config.magic,
        "comment": "trading_bot",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    ok = result is not None and result.retcode == mt5.TRADE_RETCODE_DONE
    if not ok:
        log.error("order rejected: %s", result)
    return {
        "ok": ok,
        "retcode": getattr(result, "retcode", None),
        "price": getattr(result, "price", price),
        "volume": volume,
        "direction": direction,
        "sl": stop,
        "tp": target,
        "time": datetime.now(timezone.utc).isoformat(),
    }


def close_positions(mt5, config: BotConfig, positions: list) -> None:
    for pos in positions:
        tick = mt5.symbol_info_tick(config.symbol)
        closing = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        mt5.order_send({
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": config.symbol,
            "volume": pos.volume,
            "type": closing,
            "position": pos.ticket,
            "price": tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask,
            "deviation": 20,
            "magic": config.magic,
            "comment": "trading_bot close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        })
        log.info("closed position %s", pos.ticket)


def step(mt5, config: BotConfig, state: BotState) -> dict:
    """One decision cycle: read bars, vote, reconcile the position."""
    check_safety(mt5, config, state)
    df = fetch_bars(mt5, config)
    target, votes = desired_position(df, config.strategies)
    positions = open_positions(mt5, config)
    current = 0
    if positions:
        current = 1 if positions[0].type == mt5.ORDER_TYPE_BUY else -1

    action = "hold"
    detail = {}
    if current != 0 and target != current:
        close_positions(mt5, config, positions)
        current, action = 0, "closed"
    if current == 0 and target != 0 and len(open_positions(mt5, config)) < config.max_open_positions:
        atr_value = float(atr(df, config.atr_period).iloc[-1])
        if atr_value > 0:
            info = mt5.account_info()
            stop_distance = config.stop_atr_mult * atr_value
            volume = position_size(mt5, config, info.equity, stop_distance)
            if volume > 0:
                tick = mt5.symbol_info_tick(config.symbol)
                entry = tick.ask if target > 0 else tick.bid
                stop = entry - target * stop_distance
                take = entry + target * config.target_atr_mult * atr_value
                detail = send_order(mt5, config, target, volume, stop, take)
                state.orders_sent += 1
                action = "opened" if detail["ok"] else "rejected"

    record = {
        "time": datetime.now(timezone.utc).isoformat(),
        "symbol": config.symbol,
        "votes": votes,
        "target": target,
        "action": action,
        "equity": mt5.account_info().equity,
        **detail,
    }
    state.history.append(record)
    return record
