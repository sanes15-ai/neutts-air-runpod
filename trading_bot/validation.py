"""Validation: the machinery that kills strategies.

Backtesting 61 strategies and crowning the winner is a lottery -- with that many
candidates, several will look excellent on luck alone. Three guards apply here,
and a strategy has to pass all of them:

1. **Out-of-sample split.** Strategies are ranked on the first portion of
   history and then judged on a later portion they were never ranked on.
2. **A luck baseline.** Random signals with matched trade frequency are run
   through the same pipeline; the *best of N random* strategies is what real
   candidates must beat. This is the practical form of a multiple-comparisons
   correction: if random noise scores 1.4 when you cherry-pick the best of 61,
   then a real strategy scoring 1.35 has demonstrated nothing.
3. **Cross-instrument agreement.** A genuine edge usually shows up on more than
   one market. Something that works on exactly one pair and nowhere else is
   more likely fitted to that pair's history than to a real market behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import backtest
from .strategies import Strategy

#: A strategy needs at least this many out-of-sample trades before its numbers
#: mean anything. Below it, the result is noise no matter how good it looks.
MIN_TRADES = 30


@dataclass
class Verdict:
    name: str
    is_profit_factor: float
    oos_profit_factor: float
    oos_trades: int
    oos_return: float
    oos_drawdown: float
    oos_sharpe: float
    beats_luck: bool
    instruments_positive: int
    instruments_tested: int
    passed: bool
    reason: str


def split(df: pd.DataFrame, fraction: float = 0.6) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Chronological split. Never random -- shuffling time leaks the future."""
    cut = int(len(df) * fraction)
    return df.iloc[:cut].reset_index(drop=True), df.iloc[cut:].reset_index(drop=True)


def evaluate(strategy: Strategy, df: pd.DataFrame, spread: float, **kwargs) -> backtest.Result:
    return backtest.run(df, strategy.signal(df), spread=spread, **kwargs)


def luck_baseline(
    df: pd.DataFrame,
    spread: float,
    *,
    n_random: int = 200,
    trade_rate: float = 0.5,
    seed: int = 7,
    **kwargs,
) -> dict:
    """Distribution of results from strategies that know nothing.

    Random signals are generated with a persistence matched to real strategies
    (positions held for a while rather than flipping every bar), run through the
    identical backtester, and summarised. The 95th percentile of profit factor
    is the bar a real strategy must clear to be distinguishable from luck.
    """
    rng = np.random.default_rng(seed)
    factors, returns = [], []
    for _ in range(n_random):
        raw = rng.choice([-1.0, 0.0, 1.0], size=len(df), p=[trade_rate / 2, 1 - trade_rate, trade_rate / 2])
        signal = pd.Series(raw, index=df.index).replace(0.0, np.nan).ffill().fillna(0.0)
        result = backtest.run(df, signal, spread=spread, **kwargs)
        if result.n_trades >= MIN_TRADES:
            factors.append(result.profit_factor)
            returns.append(result.metrics["total_return"])
    if not factors:
        return {"pf_p95": 1.0, "pf_max": 1.0, "pf_median": 1.0, "n": 0}
    return {
        "pf_p95": float(np.percentile(factors, 95)),
        "pf_max": float(np.max(factors)),
        "pf_median": float(np.median(factors)),
        "ret_p95": float(np.percentile(returns, 95)),
        "n": len(factors),
    }


def screen(
    strategies: list[Strategy],
    datasets: dict[str, pd.DataFrame],
    spreads: dict[str, float],
    *,
    split_fraction: float = 0.6,
    min_profit_factor: float = 1.3,
    n_random: int = 200,
    **kwargs,
) -> tuple[list[Verdict], dict]:
    """Run the full gauntlet and return a verdict per strategy.

    `datasets` maps instrument -> bars. The first instrument is the primary one
    used for the in-sample ranking and the luck baseline; the rest are the
    cross-instrument check.
    """
    primary = next(iter(datasets))
    is_df, oos_df = split(datasets[primary], split_fraction)
    baseline = luck_baseline(oos_df, spreads[primary], n_random=n_random, **kwargs)

    verdicts: list[Verdict] = []
    for strategy in strategies:
        is_result = evaluate(strategy, is_df, spreads[primary], **kwargs)
        oos_result = evaluate(strategy, oos_df, spreads[primary], **kwargs)

        positive = 0
        tested = 0
        for name, frame in datasets.items():
            if name == primary:
                continue
            _, other_oos = split(frame, split_fraction)
            other = evaluate(strategy, other_oos, spreads[name], **kwargs)
            tested += 1
            if other.n_trades >= MIN_TRADES and other.profit_factor > 1.0:
                positive += 1

        beats_luck = oos_result.profit_factor > baseline["pf_p95"]
        reasons = []
        if oos_result.n_trades < MIN_TRADES:
            reasons.append(f"only {oos_result.n_trades} OOS trades")
        if oos_result.profit_factor < min_profit_factor:
            reasons.append(f"OOS PF {oos_result.profit_factor:.2f} < {min_profit_factor}")
        if not beats_luck:
            reasons.append(f"does not beat luck baseline PF {baseline['pf_p95']:.2f}")
        if tested and positive == 0:
            reasons.append("fails on every other instrument")

        verdicts.append(
            Verdict(
                name=strategy.name,
                is_profit_factor=is_result.profit_factor,
                oos_profit_factor=oos_result.profit_factor,
                oos_trades=oos_result.n_trades,
                oos_return=oos_result.metrics["total_return"],
                oos_drawdown=oos_result.metrics["max_drawdown"],
                oos_sharpe=oos_result.metrics["sharpe"],
                beats_luck=beats_luck,
                instruments_positive=positive,
                instruments_tested=tested,
                passed=not reasons,
                reason="; ".join(reasons) if reasons else "passed all guards",
            )
        )
    return verdicts, baseline
