# Indicator strategy research + MT5 demo bot

> **Bitcoin is the better market for this system.** 17 of 61 strategies passed
> the guards on BTC versus 7 on FX, and the BTC set stays profitable through
> bear markets because it takes short positions. See *Bitcoin results* below.

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

## Bitcoin results

Screened separately, because crypto behaves differently: FX ranges and
mean-reverts, crypto trends. **Breakout strategies win on BTC; reversion
strategies win on FX.** Using the wrong set on either throws away the edge.

The validated BTC trio: `keltner_breakout` + `adx_filtered_ema` + `new_high_20`
(Sharpe 1.29, return-per-drawdown 9.45).

### Risk scaling (out-of-sample, 4 years, BTC)

| Risk/trade | Annual return | $/day on $1,000 | Max drawdown |
| --- | --- | --- | --- |
| 2% | 13.4% | $0.37 | −6.2% |
| 5% | 35.5% | $0.97 | −15.4% |
| **10%** | **76.5%** | **$2.09** | −30.1% |
| 20% | 168.0% | $4.60 | −54.1% |

Buy-and-hold over the same window returned 39.9%/yr with a **−53.1%**
drawdown. At 10% risk the system beats holding with *half* the drawdown.

### It survives bear markets

This is the part that separates a real trend system from a long-only bet:

| Period | BTC held | Strategy | Strategy max DD |
| --- | --- | --- | --- |
| 2018 crash | −72.6% | **+5.4%** | −30.6% |
| 2021 bull | +57.6% | −2.0% | −29.0% |
| 2022 bear | −65.3% | **+0.5%** | −22.0% |
| 2023–24 bull | +462.0% | +146.9% | −31.1% |
| 2025–26 | −17.7% | **+121.7%** | −22.2% |

It goes short in downtrends rather than sitting long and hoping. Its weakness
is a *choppy* bull (2021: −2.0% while BTC rose 57.6%), not a falling market.

### Costs are modelled, including swap

Average holding period is 2.9 days, so overnight financing matters but does not
dominate:

| Daily swap | Annual return | $/day |
| --- | --- | --- |
| 0.00% (unrealistic) | 76.5% | $2.09 |
| 0.02% (typical) | 71.0% | $1.94 |
| 0.05% (typical) | 63.0% | $1.73 |
| 0.10% (high/weekend) | 50.7% | $1.39 |

**Plan on ~60–70% annual at 10% risk, not 76%.**

## Position sizing: why fixed lots blow accounts

Running the same BTC/FX strategies with a **fixed 1 standard lot** on a $1,000
account, started at 60 different dates:

| Sizing | Accounts blown | Median end | Best case |
| --- | --- | --- | --- |
| 1.00 lot fixed | **27 / 60** | $3,306 | $59,998 |
| 0.10 lot fixed | 6 / 60 | $1,479 | $4,727 |
| 10% risk (ATR-sized) | **0 / 60** | $1,024 | $1,996 |

A fixed lot risks a fixed number of *pips*, which becomes an unbounded share of
a shrinking account. ATR-based sizing shrinks the position as volatility rises
and as equity falls, which is why it never blew up in 60 trials.

To earn $100 on a *winning* trade at the 3×ATR target you need roughly **0.06
lots**, risking about $67 per loss — not 1 lot, which risks $1,094 on a $1,000
account.

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
# Bitcoin (recommended - stronger edge)
python -m trading_bot.run_mt5 --symbol BTCUSD --timeframe D1 --risk 0.10

# EUR/USD
python -m trading_bot.run_mt5 --symbol EURUSD --timeframe D1 --risk 0.10
```

The strategy set is chosen automatically from the symbol: crypto symbols get
the breakout trio, everything else gets the reversion trio.

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

On **BTC** at 10% risk, the backtested return after swap costs is ~63%/year —
about **$1.73 per day** on $1,000, with a −30% drawdown along the way. On FX it
is ~18%/year, about $0.50 per day. Those are what a validated indicator edge is
worth on this capital.

Reaching **$100/day** at the BTC rate needs roughly **$53,000** of capital, not
a bigger lot size. The
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
