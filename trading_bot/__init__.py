"""Indicator strategy research framework.

Screens a library of trading strategies against historical data with realistic
costs, then applies validation guards designed to *kill* strategies that only
look good by luck: an out-of-sample split, a multiple-testing luck baseline,
and a cross-instrument check.

Nothing here places live orders.
"""

from . import backtest, data, indicators, strategies, validation

__all__ = ["backtest", "data", "indicators", "strategies", "validation"]
__version__ = "0.1.0"
