"""Solana DEX arbitrage scanner.

Finds round-trip (SOL -> token -> SOL) price dislocations by pricing both legs
through the Jupiter aggregator, nets out transaction, priority and tip costs,
and records anything that clears a configured edge threshold.

Detection and paper trading are the default. Live swap submission requires an
explicit opt-in and is guarded by hard limits in :mod:`arbitrage_bot.executor`.
"""

from .config import Config, ConfigError, TokenConfig, load_config
from .detector import Leg, Opportunity, evaluate_cycle, scan
from .executor import LiveExecutor, PaperExecutor, RiskLimitExceeded
from .jupiter import JupiterClient, QuoteError
from .ledger import Ledger

__all__ = [
    "Config",
    "ConfigError",
    "TokenConfig",
    "load_config",
    "Leg",
    "Opportunity",
    "evaluate_cycle",
    "scan",
    "JupiterClient",
    "QuoteError",
    "PaperExecutor",
    "LiveExecutor",
    "RiskLimitExceeded",
    "Ledger",
]

__version__ = "0.1.0"
