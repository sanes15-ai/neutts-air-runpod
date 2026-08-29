"""Strategy library.

Every strategy is a pure function `df -> position series` in {-1, 0, +1},
decided at each bar's close. The backtester handles execution, costs and stops,
so a strategy here only ever expresses an opinion -- it cannot cheat on fills.

Each entry declares a `regime` it is *expected* to suit. That expectation is a
hypothesis to be tested per regime, never an excuse: a strategy that only works
in the regime it claims still has to prove it out of sample.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from . import indicators as ind

SignalFn = Callable[[pd.DataFrame], pd.Series]

TREND, REVERSION, BREAKOUT, COMBO = "trend", "reversion", "breakout", "combo"


@dataclass(frozen=True)
class Strategy:
    name: str
    family: str
    regime: str
    fn: SignalFn

    def signal(self, df: pd.DataFrame) -> pd.Series:
        out = self.fn(df).reindex(df.index).fillna(0.0)
        return out.clip(-1, 1)


REGISTRY: dict[str, Strategy] = {}


def register(name: str, family: str, regime: str):
    def wrap(fn: SignalFn) -> SignalFn:
        if name in REGISTRY:
            raise ValueError(f"duplicate strategy name {name!r}")
        REGISTRY[name] = Strategy(name, family, regime, fn)
        return fn

    return wrap


def _sign(series: pd.Series) -> pd.Series:
    return pd.Series(np.sign(series.to_numpy()), index=series.index)


# --------------------------------------------------------------------------
# Trend following: hold with the direction, accept many small losses in chop.
# --------------------------------------------------------------------------

def _ma_cross(fast: int, slow: int, kind=ind.sma) -> SignalFn:
    def fn(df):
        return _sign(kind(df["close"], fast) - kind(df["close"], slow))
    return fn


for _f, _s in [(10, 30), (20, 50), (50, 200), (5, 20), (30, 100)]:
    register(f"sma_cross_{_f}_{_s}", "ma_cross", TREND)(_ma_cross(_f, _s, ind.sma))
for _f, _s in [(9, 21), (12, 26), (8, 34), (21, 55)]:
    register(f"ema_cross_{_f}_{_s}", "ma_cross", TREND)(_ma_cross(_f, _s, ind.ema))


@register("macd_signal_cross", "macd", TREND)
def _macd_signal(df):
    line, sig, _ = ind.macd(df["close"])
    return _sign(line - sig)


@register("macd_zero_cross", "macd", TREND)
def _macd_zero(df):
    line, _, _ = ind.macd(df["close"])
    return _sign(line)


@register("macd_hist_slope", "macd", TREND)
def _macd_hist(df):
    _, _, hist = ind.macd(df["close"])
    return _sign(hist.diff())


def _supertrend(period: int, mult: float) -> SignalFn:
    def fn(df):
        return ind.supertrend(df, period, mult)
    return fn


for _p, _m in [(10, 3.0), (7, 2.0), (14, 4.0)]:
    register(f"supertrend_{_p}_{_m:g}", "supertrend", TREND)(_supertrend(_p, _m))


@register("price_vs_ema200", "filter", TREND)
def _price_ema200(df):
    return _sign(df["close"] - ind.ema(df["close"], 200))


@register("triple_ema_stack", "ma_cross", TREND)
def _triple_ema(df):
    e1, e2, e3 = (ind.ema(df["close"], p) for p in (10, 20, 40))
    long = (e1 > e2) & (e2 > e3)
    short = (e1 < e2) & (e2 < e3)
    return pd.Series(np.where(long, 1.0, np.where(short, -1.0, 0.0)), index=df.index)


@register("linreg_slope_20", "slope", TREND)
def _linreg(df):
    slope = df["close"].rolling(20, min_periods=20).apply(
        lambda w: np.polyfit(np.arange(len(w)), w, 1)[0], raw=True
    )
    return _sign(slope)


@register("adx_filtered_ema", "filter", TREND)
def _adx_ema(df):
    direction = _sign(ind.ema(df["close"], 12) - ind.ema(df["close"], 26))
    return direction.where(ind.adx(df) > 25, 0.0)


# --------------------------------------------------------------------------
# Mean reversion: fade extremes, expect many small wins and rare large losses.
# --------------------------------------------------------------------------

def _rsi_revert(period: int, low: float, high: float) -> SignalFn:
    def fn(df):
        r = ind.rsi(df["close"], period)
        return pd.Series(np.where(r < low, 1.0, np.where(r > high, -1.0, 0.0)), index=df.index)
    return fn


for _p, _lo, _hi in [(2, 10, 90), (14, 30, 70), (14, 20, 80), (7, 25, 75), (21, 35, 65)]:
    register(f"rsi{_p}_revert_{int(_lo)}_{int(_hi)}", "rsi", REVERSION)(_rsi_revert(_p, _lo, _hi))


def _bb_revert(period: int, mult: float) -> SignalFn:
    def fn(df):
        lower, _, upper = ind.bollinger(df["close"], period, mult)
        return pd.Series(
            np.where(df["close"] < lower, 1.0, np.where(df["close"] > upper, -1.0, 0.0)),
            index=df.index,
        )
    return fn


for _p, _m in [(20, 2.0), (20, 2.5), (10, 2.0), (50, 2.0)]:
    register(f"bb_revert_{_p}_{_m:g}", "bollinger", REVERSION)(_bb_revert(_p, _m))


def _zscore_revert(period: int, threshold: float) -> SignalFn:
    def fn(df):
        z = ind.zscore(df["close"], period)
        return pd.Series(
            np.where(z < -threshold, 1.0, np.where(z > threshold, -1.0, 0.0)), index=df.index
        )
    return fn


for _p, _t in [(20, 2.0), (50, 2.0), (100, 2.5)]:
    register(f"zscore_revert_{_p}_{_t:g}", "zscore", REVERSION)(_zscore_revert(_p, _t))


@register("stoch_revert_20_80", "stochastic", REVERSION)
def _stoch_revert(df):
    k, d = ind.stochastic(df)
    return pd.Series(np.where(k < 20, 1.0, np.where(k > 80, -1.0, 0.0)), index=df.index)


@register("stoch_cross", "stochastic", REVERSION)
def _stoch_cross(df):
    k, d = ind.stochastic(df)
    return _sign(k - d)


@register("cci_revert_100", "cci", REVERSION)
def _cci_revert(df):
    c = ind.cci(df)
    return pd.Series(np.where(c < -100, 1.0, np.where(c > 100, -1.0, 0.0)), index=df.index)


@register("cci_revert_200", "cci", REVERSION)
def _cci_revert2(df):
    c = ind.cci(df)
    return pd.Series(np.where(c < -200, 1.0, np.where(c > 200, -1.0, 0.0)), index=df.index)


@register("williams_revert", "williams", REVERSION)
def _williams(df):
    w = ind.williams_r(df)
    return pd.Series(np.where(w < -80, 1.0, np.where(w > -20, -1.0, 0.0)), index=df.index)


@register("keltner_revert", "keltner", REVERSION)
def _keltner_revert(df):
    lower, _, upper = ind.keltner(df)
    return pd.Series(
        np.where(df["close"] < lower, 1.0, np.where(df["close"] > upper, -1.0, 0.0)),
        index=df.index,
    )


@register("consecutive_down_3", "pattern", REVERSION)
def _consec_down(df):
    down = (df["close"] < df["close"].shift(1)).rolling(3, min_periods=3).sum()
    up = (df["close"] > df["close"].shift(1)).rolling(3, min_periods=3).sum()
    return pd.Series(np.where(down == 3, 1.0, np.where(up == 3, -1.0, 0.0)), index=df.index)


@register("pct_from_sma20", "distance", REVERSION)
def _pct_sma(df):
    dist = (df["close"] - ind.sma(df["close"], 20)) / ind.sma(df["close"], 20)
    return pd.Series(np.where(dist < -0.02, 1.0, np.where(dist > 0.02, -1.0, 0.0)), index=df.index)


# --------------------------------------------------------------------------
# Breakout / momentum: buy strength, expecting continuation.
# --------------------------------------------------------------------------

def _donchian(period: int) -> SignalFn:
    def fn(df):
        low, high = ind.donchian(df, period)
        # Compare against the *previous* bar's channel; using this bar's own
        # high would make every breakout trivially true.
        return pd.Series(
            np.where(df["close"] > high.shift(1), 1.0,
                     np.where(df["close"] < low.shift(1), -1.0, 0.0)),
            index=df.index,
        ).replace(0.0, np.nan).ffill().fillna(0.0)
    return fn


for _p in (10, 20, 55):
    register(f"donchian_breakout_{_p}", "donchian", BREAKOUT)(_donchian(_p))


def _roc_momentum(period: int) -> SignalFn:
    def fn(df):
        return _sign(ind.roc(df["close"], period))
    return fn


for _p in (5, 10, 20, 60):
    register(f"roc_momentum_{_p}", "momentum", BREAKOUT)(_roc_momentum(_p))


@register("keltner_breakout", "keltner", BREAKOUT)
def _keltner_break(df):
    lower, _, upper = ind.keltner(df)
    return pd.Series(
        np.where(df["close"] > upper, 1.0, np.where(df["close"] < lower, -1.0, 0.0)),
        index=df.index,
    )


@register("bb_squeeze_breakout", "bollinger", BREAKOUT)
def _squeeze(df):
    lower, mid, upper = ind.bollinger(df["close"], 20, 2.0)
    width = (upper - lower) / mid
    tight = width < width.rolling(50, min_periods=50).quantile(0.25)
    direction = np.where(df["close"] > upper, 1.0, np.where(df["close"] < lower, -1.0, 0.0))
    return pd.Series(np.where(tight.shift(1).fillna(False), direction, 0.0), index=df.index)


@register("atr_channel_breakout", "atr", BREAKOUT)
def _atr_break(df):
    a = ind.atr(df)
    upper = df["close"].shift(1) + 1.5 * a
    lower = df["close"].shift(1) - 1.5 * a
    return pd.Series(
        np.where(df["close"] > upper, 1.0, np.where(df["close"] < lower, -1.0, 0.0)),
        index=df.index,
    )


@register("new_high_20", "pattern", BREAKOUT)
def _new_high(df):
    high20 = df["high"].rolling(20, min_periods=20).max().shift(1)
    low20 = df["low"].rolling(20, min_periods=20).min().shift(1)
    return pd.Series(
        np.where(df["close"] > high20, 1.0, np.where(df["close"] < low20, -1.0, 0.0)),
        index=df.index,
    )


@register("momentum_12_1", "momentum", BREAKOUT)
def _mom_12_1(df):
    # Classic academic momentum: 12-period return skipping the most recent bar,
    # which avoids the short-term reversal effect that contaminates it.
    return _sign(df["close"].shift(1) / df["close"].shift(13) - 1)


@register("vol_expansion", "atr", BREAKOUT)
def _vol_expansion(df):
    a = ind.atr(df)
    expanding = a > a.rolling(20, min_periods=20).mean() * 1.2
    return _sign(df["close"].diff()).where(expanding, 0.0)


# --------------------------------------------------------------------------
# Combos: one indicator gates another. These are the regime-aware ones.
# --------------------------------------------------------------------------

@register("ema_cross_adx_gate", "combo", COMBO)
def _ema_adx(df):
    direction = _sign(ind.ema(df["close"], 9) - ind.ema(df["close"], 21))
    return direction.where(ind.adx(df) > 20, 0.0)


@register("rsi_revert_trend_gate", "combo", COMBO)
def _rsi_trend(df):
    trend = _sign(df["close"] - ind.ema(df["close"], 200))
    r = ind.rsi(df["close"], 14)
    # Only buy dips in an uptrend / sell rallies in a downtrend.
    long = (trend > 0) & (r < 35)
    short = (trend < 0) & (r > 65)
    return pd.Series(np.where(long, 1.0, np.where(short, -1.0, 0.0)), index=df.index)


@register("bb_revert_low_adx", "combo", COMBO)
def _bb_low_adx(df):
    lower, _, upper = ind.bollinger(df["close"], 20, 2.0)
    base = pd.Series(
        np.where(df["close"] < lower, 1.0, np.where(df["close"] > upper, -1.0, 0.0)),
        index=df.index,
    )
    # Mean reversion needs a range: suppress it when ADX says a trend is running.
    return base.where(ind.adx(df) < 20, 0.0)


@register("supertrend_rsi_confirm", "combo", COMBO)
def _st_rsi(df):
    st = ind.supertrend(df, 10, 3.0)
    r = ind.rsi(df["close"], 14)
    return pd.Series(
        np.where((st > 0) & (r > 50), 1.0, np.where((st < 0) & (r < 50), -1.0, 0.0)),
        index=df.index,
    )


@register("macd_stoch_confirm", "combo", COMBO)
def _macd_stoch(df):
    line, sig, _ = ind.macd(df["close"])
    k, _d = ind.stochastic(df)
    return pd.Series(
        np.where((line > sig) & (k < 80), 1.0, np.where((line < sig) & (k > 20), -1.0, 0.0)),
        index=df.index,
    )


@register("donchian_adx_gate", "combo", COMBO)
def _don_adx(df):
    base = REGISTRY["donchian_breakout_20"].fn(df)
    return base.where(ind.adx(df) > 25, 0.0)


@register("trend_high_vol_only", "combo", COMBO)
def _trend_highvol(df):
    direction = _sign(ind.ema(df["close"], 12) - ind.ema(df["close"], 26))
    vol = ind.realized_vol(df["close"], 20)
    return direction.where(vol > vol.rolling(100, min_periods=100).median(), 0.0)


@register("revert_low_vol_only", "combo", COMBO)
def _revert_lowvol(df):
    r = ind.rsi(df["close"], 14)
    base = pd.Series(np.where(r < 30, 1.0, np.where(r > 70, -1.0, 0.0)), index=df.index)
    vol = ind.realized_vol(df["close"], 20)
    return base.where(vol < vol.rolling(100, min_periods=100).median(), 0.0)


@register("triple_confirm", "combo", COMBO)
def _triple_confirm(df):
    trend = ind.ema(df["close"], 50) > ind.ema(df["close"], 200)
    momentum = ind.roc(df["close"], 10) > 0
    strength = ind.adx(df) > 20
    long = trend & momentum & strength
    short = (~trend) & (~momentum) & strength
    return pd.Series(np.where(long, 1.0, np.where(short, -1.0, 0.0)), index=df.index)


def all_strategies() -> list[Strategy]:
    return list(REGISTRY.values())
