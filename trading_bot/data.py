"""Historical OHLCV loading, with a local cache.

Data comes from Yahoo Finance's chart endpoint: free, no key, and good enough
for strategy research. It is *not* broker data -- your Exness fills will differ,
which is exactly why a strategy that survives here still has to prove itself on
a demo account before it means anything.
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

import pandas as pd

CACHE_DIR = Path(__file__).resolve().parent / "cache"

#: Yahoo symbol per instrument. FX pairs use the '=X' suffix.
SYMBOLS = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "JPY=X",
    "AUDUSD": "AUDUSD=X",
    "USDCHF": "CHF=X",
    "USDCAD": "CAD=X",
    "XAUUSD": "GC=F",
    # Crypto trades 24/7 and trends far harder than FX, so it is worth testing
    # separately rather than assuming FX-tuned strategies carry over.
    "BTCUSD": "BTC-USD",
    "ETHUSD": "ETH-USD",
}

#: Typical Exness-style round-trip cost per trade, in price units, by instrument.
#: Deliberately pessimistic: real spreads widen on news and overnight.
SPREAD = {
    "EURUSD": 0.00012,
    "GBPUSD": 0.00016,
    "USDJPY": 0.015,
    "AUDUSD": 0.00014,
    "USDCHF": 0.00016,
    "USDCAD": 0.00018,
    "XAUUSD": 0.35,
    # Crypto CFD spreads are far wider than FX in relative terms, and widen
    # sharply in the volatility these strategies are meant to trade.
    "BTCUSD": 25.0,
    "ETHUSD": 1.5,
}


class DataError(RuntimeError):
    """Raised when history cannot be fetched or is unusable."""


def _fetch(symbol: str, range_: str, interval: str) -> pd.DataFrame:
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?range={range_}&interval={interval}"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode())
    except Exception as exc:  # noqa: BLE001 - surface any transport failure the same way
        raise DataError(f"fetch failed for {symbol}: {exc}") from exc

    result = (payload.get("chart") or {}).get("result")
    if not result:
        raise DataError(f"no data returned for {symbol}: {payload.get('chart')}")
    block = result[0]
    quote = block["indicators"]["quote"][0]
    frame = pd.DataFrame(
        {
            "time": pd.to_datetime(block["timestamp"], unit="s", utc=True),
            "open": quote["open"],
            "high": quote["high"],
            "low": quote["low"],
            "close": quote["close"],
        }
    )
    # Yahoo emits nulls for illiquid stamps; a bar with no price is not a bar.
    frame = frame.dropna().reset_index(drop=True)
    if len(frame) < 100:
        raise DataError(f"{symbol}: only {len(frame)} usable bars")
    return frame


def load(
    instrument: str,
    *,
    interval: str = "1d",
    range_: str = "10y",
    refresh: bool = False,
) -> pd.DataFrame:
    """Return OHLCV bars, fetching and caching on first use.

    Yahoo caps intraday history: '1h' goes back ~730 days, '1d' much further.
    """
    if instrument not in SYMBOLS:
        raise DataError(f"unknown instrument {instrument!r}; known: {sorted(SYMBOLS)}")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{instrument}_{interval}_{range_}.csv"
    if path.exists() and not refresh:
        frame = pd.read_csv(path, parse_dates=["time"])
        if len(frame) >= 100:
            return frame
    frame = _fetch(SYMBOLS[instrument], range_, interval)
    frame.to_csv(path, index=False)
    return frame


def load_many(instruments, **kwargs) -> dict[str, pd.DataFrame]:
    """Load several instruments, skipping any that fail rather than aborting."""
    out = {}
    for name in instruments:
        try:
            out[name] = load(name, **kwargs)
        except DataError as exc:
            print(f"  skip {name}: {exc}")
        time.sleep(0.3)  # be polite to the endpoint
    return out
