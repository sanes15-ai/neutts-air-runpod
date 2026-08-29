"""Technical indicators.

All functions take and return pandas Series/DataFrames and are strictly causal:
the value at bar *i* uses only data up to and including bar *i*. Any indicator
that peeks ahead would manufacture profit that cannot exist live, so every
rolling window here is backward-looking and nothing is centred or shifted
negatively.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI. Returns 0-100; 50 means no net directional pressure."""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100 - (100 / (1 + rs))
    # A window with no losses divides by zero above. That is maximally
    # overbought (100), not undefined -- but only once warmup has completed;
    # genuine warmup bars must stay NaN so no strategy trades on them.
    warm = avg_gain.notna()
    return out.where(~(warm & out.isna()), 100.0)


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average true range -- the volatility unit used for stops and sizing."""
    return true_range(df).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def bollinger(series: pd.Series, period: int = 20, mult: float = 2.0):
    mid = sma(series, period)
    sd = series.rolling(period, min_periods=period).std(ddof=0)
    return mid - mult * sd, mid, mid + mult * sd


def keltner(df: pd.DataFrame, period: int = 20, mult: float = 2.0):
    mid = ema(df["close"], period)
    width = mult * atr(df, period)
    return mid - width, mid, mid + width


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    line = ema(series, fast) - ema(series, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return line, sig, line - sig


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Trend *strength* regardless of direction. Above ~25 is a real trend."""
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = true_range(df).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(
        alpha=1 / period, adjust=False, min_periods=period
    ).mean() / tr.replace(0.0, np.nan)
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(
        alpha=1 / period, adjust=False, min_periods=period
    ).mean() / tr.replace(0.0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def stochastic(df: pd.DataFrame, period: int = 14, smooth: int = 3):
    low = df["low"].rolling(period, min_periods=period).min()
    high = df["high"].rolling(period, min_periods=period).max()
    k = 100 * (df["close"] - low) / (high - low).replace(0.0, np.nan)
    return k, k.rolling(smooth, min_periods=smooth).mean()


def cci(df: pd.DataFrame, period: int = 20) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    mean = tp.rolling(period, min_periods=period).mean()
    dev = (tp - mean).abs().rolling(period, min_periods=period).mean()
    return (tp - mean) / (0.015 * dev.replace(0.0, np.nan))


def williams_r(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"].rolling(period, min_periods=period).max()
    low = df["low"].rolling(period, min_periods=period).min()
    return -100 * (high - df["close"]) / (high - low).replace(0.0, np.nan)


def donchian(df: pd.DataFrame, period: int = 20):
    return (
        df["low"].rolling(period, min_periods=period).min(),
        df["high"].rolling(period, min_periods=period).max(),
    )


def zscore(series: pd.Series, period: int = 20) -> pd.Series:
    mean = series.rolling(period, min_periods=period).mean()
    sd = series.rolling(period, min_periods=period).std(ddof=0)
    return (series - mean) / sd.replace(0.0, np.nan)


def roc(series: pd.Series, period: int = 10) -> pd.Series:
    return 100 * (series / series.shift(period) - 1)


def supertrend(df: pd.DataFrame, period: int = 10, mult: float = 3.0) -> pd.Series:
    """Returns +1 while in an uptrend, -1 in a downtrend.

    The band ratchets: it only ever tightens toward price within a trend, which
    is what makes it a trailing regime flag rather than a noisy oscillator.
    """
    hl2 = (df["high"] + df["low"]) / 2
    band = mult * atr(df, period)
    upper = (hl2 + band).to_numpy(copy=True)
    lower = (hl2 - band).to_numpy(copy=True)
    close = df["close"].to_numpy()
    direction = np.ones(len(df))
    for i in range(1, len(df)):
        if np.isnan(upper[i]) or np.isnan(upper[i - 1]):
            continue
        upper[i] = min(upper[i], upper[i - 1]) if close[i - 1] <= upper[i - 1] else upper[i]
        lower[i] = max(lower[i], lower[i - 1]) if close[i - 1] >= lower[i - 1] else lower[i]
        if close[i] > upper[i - 1]:
            direction[i] = 1
        elif close[i] < lower[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
    return pd.Series(direction, index=df.index)


def realized_vol(series: pd.Series, period: int = 20) -> pd.Series:
    """Rolling standard deviation of returns -- the volatility regime input."""
    return series.pct_change().rolling(period, min_periods=period).std(ddof=0)
