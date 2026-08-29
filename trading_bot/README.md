# Indicator strategy research + MT5 demo bot

Screens a 61-strategy library against real market data with realistic costs,
applies validation guards designed to **kill** strategies rather than crown
them, and runs the survivors on a MetaTrader 5 **demo** account.

## The headline result

61 strategies, 10 years of daily data, 6 instruments, out-of-sample validated:

| | |
| --- | --- |
| Strategies tested | 61 |
| Passed all guards | **7** |
| Cleared the multiple-testing bar *and* worked on 2+ other pairs | **5** |
| Best validated return | **2.8% / year** at 1% risk per trade |
| Best trio (diversified) | **Sharpe 1.23, −1.3% max drawdown** |

**The luck bar.** Picking the best of 61 *random* strategies scores a profit
factor of **1.33**. Any strategy below that is indistinguishable from lucky
noise — which is why 54 of 61 were rejected, including MACD crossover,
Bollinger reversion, Stochastic, and every Supertrend variant.

In-sample to out-of-sample correlation of profit factor was only **+0.41**:
backtest performance is a weak predictor of future performance even on the same
instrument. Plan accordingly.

## The validated trio

Selected by return-per-drawdown across all 35 possible trios, not by raw return:

| Strategy | Type | OOS PF | Trades |
| --- | --- | --- | --- |
| `keltner_revert` | mean reversion | 3.65 | 34 |
| `rsi7_revert_25_75` | mean reversion | 1.97 | 66 |
| `roc_momentum_20` | momentum | 1.37 | 108 |

They work together because the two mean-reversion strategies are **negatively
correlated (−0.27, −0.31)** with the momentum one. The combination has more
than double the Sharpe of any single trend strategy at a sixth of the drawdown.

### Risk scaling (out-of-sample, EURUSD)

| Risk/trade | Annual return | Max drawdown | Sharpe |
| --- | --- | --- | --- |
| 1% | 2.0% | −1.3% | 1.23 |
| 5% | 9.8% | −6.7% | 1.16 |
| **10%** | **18.3%** | **−15.1%** | **1.10** |
| 20% | 30.4% | −31.7% | 1.05 |

Sharpe stays flat while drawdown scales linearly — risk is a volume knob, not
an edge knob. 10% is the aggressive-but-survivable default.

### The caveat that matters

Trading this trio across **all six pairs** dropped the Sharpe from 1.23 to
**0.38**. The edge is partly EURUSD-specific, which is a real overfitting
warning. Expect live results somewhere between those two numbers, and treat the
demo run as the experiment that decides which.

## Running the research

```bash
pip install numpy pandas
python -m unittest discover -s trading_bot/tests -t .   # 26 tests
```

```python
from trading_bot import data, strategies, validation
ds = data.load_many(["EURUSD", "GBPUSD"], interval="1d", range_="10y")
verdicts, baseline = validation.screen(
    strategies.all_strategies(), ds, {n: data.SPREAD[n] for n in ds}
)
```

## Running the demo bot

The `MetaTrader5` package is **Windows-only** and needs the terminal running on
the same machine, so this part runs on your PC, not in a container.

1. Install MT5 and log into your **Exness demo** account.
2. Enable the *Algo Trading* button in the toolbar.
3. `pip install MetaTrader5 numpy pandas`
4. Run:

```bash
python -m trading_bot.run_mt5 --symbol EURUSD --timeframe D1 --risk 0.10
```

Every decision is appended to `mt5_trades.jsonl` for later analysis.

### Safety properties

| Guard | Behaviour |
| --- | --- |
| Demo check | Refuses to trade unless the terminal reports a demo account |
| Equity floor | Halts below 60% of starting equity |
| Daily loss limit | Halts after −15% in one day |
| Stops | Every order carries an ATR stop *and* target, set before sending |
| Forming bar | The incomplete final bar is discarded — no live lookahead |

There is no accidental path to a real account: `--i-understand-live` must be
passed explicitly, and you should not pass it.

## Honest expectations

At 10% risk on $1,000, the backtested return is ~18%/year — about **$0.50 per
day**. That is what a validated indicator edge is worth on this capital. The
purpose of the demo run is not income; it is to find out whether the
out-of-sample edge survives contact with live spreads, slippage and gaps.

If it does, the way to more money is **more capital**, not more risk.

## Layout

| File | Role |
| --- | --- |
| `data.py` | Historical OHLCV with caching |
| `indicators.py` | Causal indicator library |
| `strategies.py` | 61 strategies in a registry |
| `backtest.py` | Event-driven engine: next-bar fills, spread, intrabar stops |
| `validation.py` | OOS split, luck baseline, cross-instrument check |
| `portfolio.py` | Multi-strategy combination |
| `mt5_bot.py` | Live demo trading logic + safety guards |
| `run_mt5.py` | CLI entry point |
