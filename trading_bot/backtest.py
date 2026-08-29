"""Event-driven backtest with realistic costs.

Three rules make the results honest, and all three are enforced here rather
than left to each strategy:

1. **No lookahead.** A signal computed from bar *i* is executed at the *open of
   bar i+1*. A strategy physically cannot trade on a close it has not seen yet.
2. **Costs on every trade.** The full spread is charged per round trip, plus
   optional slippage. Nothing is reported as profit until it has paid to get in
   and out.
3. **Stops are checked intrabar** against the bar's high/low, so a trade that
   would have been stopped out mid-bar is not allowed to survive to the close.

Where a bar's high and low would *both* trigger the stop and the target, the
stop is taken. That is the pessimistic assumption, and being wrong in the
pessimistic direction is the only kind of wrong that is safe here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .indicators import atr


@dataclass
class Trade:
    entry_index: int
    exit_index: int
    direction: int
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    reason: str
    bars_held: int


@dataclass
class Result:
    """Backtest outcome. `metrics` is what decides a strategy's fate."""

    trades: list[Trade] = field(default_factory=list)
    equity: pd.Series = field(default_factory=pd.Series)
    metrics: dict = field(default_factory=dict)

    @property
    def profit_factor(self) -> float:
        return self.metrics.get("profit_factor", 0.0)

    @property
    def n_trades(self) -> int:
        return len(self.trades)


def _metrics(trades: list[Trade], equity: pd.Series, initial: float) -> dict:
    if not trades:
        return {
            "n_trades": 0, "profit_factor": 0.0, "win_rate": 0.0, "expectancy": 0.0,
            "total_return": 0.0, "max_drawdown": 0.0, "sharpe": 0.0, "final_equity": initial,
        }
    pnls = np.array([t.pnl for t in trades])
    wins, losses = pnls[pnls > 0], pnls[pnls < 0]
    gross_win, gross_loss = wins.sum(), -losses.sum()
    # A run with no losing trade has infinite profit factor, which is a sample-size
    # artefact, not an edge. Cap it so it cannot flatter a 3-trade strategy.
    pf = gross_win / gross_loss if gross_loss > 0 else (99.0 if gross_win > 0 else 0.0)

    peak = equity.cummax()
    drawdown = (equity - peak) / peak
    returns = equity.pct_change().dropna()
    # Daily bars -> annualise by sqrt(252). Sharpe on a tiny sample is noise;
    # it is reported for ranking, never as proof on its own.
    sharpe = (
        float(returns.mean() / returns.std(ddof=0) * np.sqrt(252))
        if len(returns) > 1 and returns.std(ddof=0) > 0
        else 0.0
    )
    return {
        "n_trades": len(trades),
        "profit_factor": float(pf),
        "win_rate": float(len(wins) / len(trades)),
        "expectancy": float(pnls.mean()),
        "total_return": float(equity.iloc[-1] / initial - 1),
        "max_drawdown": float(drawdown.min()),
        "sharpe": sharpe,
        "final_equity": float(equity.iloc[-1]),
        "avg_win": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.mean()) if len(losses) else 0.0,
        "avg_bars_held": float(np.mean([t.bars_held for t in trades])),
    }


def run(
    df: pd.DataFrame,
    signal: pd.Series,
    *,
    spread: float,
    initial_equity: float = 1000.0,
    risk_per_trade: float = 0.01,
    stop_atr_mult: float = 2.0,
    target_atr_mult: float = 3.0,
    atr_period: int = 14,
    slippage: float = 0.0,
    max_bars: int | None = None,
    fixed_size: float | None = None,
) -> Result:
    """Backtest a target-position series.

    If `fixed_size` is given (in units -- 100_000 is one standard FX lot), every
    trade uses that size regardless of equity or volatility. This is how most
    retail accounts are actually traded, and modelling it is the fastest way to
    see why they do not survive: a fixed lot risks a fixed *number of pips*,
    which becomes an unbounded fraction of a shrinking account.

    `signal` holds the desired position (-1 short, 0 flat, +1 long) as decided
    at each bar's close; execution happens at the next bar's open.

    Sizing is risk-based: each trade risks `risk_per_trade` of current equity,
    with the stop placed `stop_atr_mult` ATRs away. That keeps position size
    proportional to volatility instead of betting a fixed lot into any
    conditions -- the single biggest difference between an account that
    survives a bad month and one that does not.
    """
    if len(df) != len(signal):
        raise ValueError("signal must align with df")

    open_ = df["open"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    atr_values = atr(df, atr_period).to_numpy(dtype=float)
    target = signal.fillna(0).to_numpy(dtype=float)

    equity = initial_equity
    equity_curve = np.full(len(df), initial_equity, dtype=float)
    trades: list[Trade] = []

    position = 0          # -1 / 0 / +1
    entry_price = 0.0
    entry_index = 0
    size = 0.0
    stop = 0.0
    target_price = 0.0

    def close_trade(i: int, price: float, reason: str) -> None:
        nonlocal equity, position, size
        pnl = (price - entry_price) * position * size - spread * size - slippage * size
        equity += pnl
        trades.append(
            Trade(entry_index, i, position, entry_price, price, size, pnl, reason,
                  i - entry_index)
        )
        position, size = 0, 0.0

    for i in range(1, len(df)):
        # A margin call ends the account. Without this the simulation happily
        # "recovers" from negative equity, which no real broker permits.
        if equity <= 0:
            equity_curve[i:] = 0.0
            break

        # --- manage an open position inside this bar, before any new signal ---
        if position != 0:
            hit_stop = low[i] <= stop if position > 0 else high[i] >= stop
            hit_target = high[i] >= target_price if position > 0 else low[i] <= target_price
            if hit_stop:                      # pessimistic: stop wins ties
                close_trade(i, stop, "stop")
            elif hit_target:
                close_trade(i, target_price, "target")
            elif max_bars is not None and i - entry_index >= max_bars:
                close_trade(i, open_[i], "time")

        # --- act on the signal decided at the PREVIOUS close ---
        desired = int(target[i - 1])
        if position != 0 and desired != position:
            close_trade(i, open_[i], "signal")
        if position == 0 and desired != 0 and not np.isnan(atr_values[i - 1]):
            stop_distance = stop_atr_mult * atr_values[i - 1]
            if stop_distance > 0:
                # Risk a fixed fraction of equity: size = risk$ / stop distance.
                size = (
                    fixed_size
                    if fixed_size is not None
                    else (equity * risk_per_trade) / stop_distance
                )
                position = desired
                entry_price = open_[i]
                entry_index = i
                stop = entry_price - desired * stop_distance
                target_price = entry_price + desired * target_atr_mult * atr_values[i - 1]

        # Mark to market so drawdown reflects open risk, not just closed trades.
        unrealised = (close[i] - entry_price) * position * size if position else 0.0
        equity_curve[i] = equity + unrealised

    if position != 0:
        close_trade(len(df) - 1, close[-1], "eod")
        equity_curve[-1] = equity

    curve = pd.Series(equity_curve, index=df.index)
    return Result(trades=trades, equity=curve, metrics=_metrics(trades, curve, initial_equity))
