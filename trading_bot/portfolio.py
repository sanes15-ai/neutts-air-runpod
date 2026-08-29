"""Run several strategies together and measure the combined result.

Diversification is the one genuinely free improvement available: strategies
whose losing periods do not coincide produce a smoother combined equity curve
than any of them alone. A smoother curve means the same total drawdown budget
buys more risk per strategy -- which is the only honest way to raise returns
without simply raising the odds of ruin.

Capital is split equally across strategies, so each runs on its own sub-account
and no strategy can consume another's budget.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import backtest
from .strategies import Strategy


def run(
    df: pd.DataFrame,
    strategies: list[Strategy],
    *,
    spread: float,
    initial_equity: float = 1000.0,
    risk_per_trade: float = 0.01,
    **kwargs,
) -> dict:
    """Equal-weight portfolio backtest. Returns combined metrics and the curve."""
    if not strategies:
        raise ValueError("need at least one strategy")
    slice_equity = initial_equity / len(strategies)
    curves, results = [], {}
    for strategy in strategies:
        result = backtest.run(
            df,
            strategy.signal(df),
            spread=spread,
            initial_equity=slice_equity,
            risk_per_trade=risk_per_trade,
            **kwargs,
        )
        curves.append(result.equity)
        results[strategy.name] = result

    combined = pd.concat(curves, axis=1).sum(axis=1)
    returns = combined.pct_change().dropna()
    peak = combined.cummax()
    drawdown = ((combined - peak) / peak).min()
    total_return = combined.iloc[-1] / initial_equity - 1
    sharpe = (
        float(returns.mean() / returns.std(ddof=0) * np.sqrt(252))
        if len(returns) > 1 and returns.std(ddof=0) > 0
        else 0.0
    )
    trades = sum(r.n_trades for r in results.values())
    wins = sum(1 for r in results.values() for t in r.trades if t.pnl > 0)
    gross_win = sum(t.pnl for r in results.values() for t in r.trades if t.pnl > 0)
    gross_loss = -sum(t.pnl for r in results.values() for t in r.trades if t.pnl < 0)

    return {
        "equity": combined,
        "per_strategy": results,
        "total_return": float(total_return),
        "max_drawdown": float(drawdown),
        "sharpe": sharpe,
        "n_trades": trades,
        "win_rate": wins / trades if trades else 0.0,
        "profit_factor": float(gross_win / gross_loss) if gross_loss > 0 else 0.0,
        # Return per unit of pain: the metric that actually matters when
        # choosing how much risk to run.
        "return_over_drawdown": float(total_return / abs(drawdown)) if drawdown < 0 else 0.0,
    }
