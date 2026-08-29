"""Configuration loading and validation.

Config is plain JSON (YAML is accepted when PyYAML is installed, so the core
package stays dependency-free). Secrets never live in the file: the wallet
keypair path and any RPC credentials come from environment variables.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

LAMPORTS_PER_SOL = 1_000_000_000
#: Solana's flat per-signature fee. Each leg of a round trip pays it.
BASE_SIGNATURE_FEE_LAMPORTS = 5_000
WRAPPED_SOL_MINT = "So11111111111111111111111111111111111111112"


class ConfigError(ValueError):
    """Raised when a config file is missing required fields or is inconsistent."""


@dataclass(frozen=True)
class TokenConfig:
    """A token to route through on the middle leg of a cycle."""

    symbol: str
    mint: str
    decimals: int = 6

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ConfigError("token entry is missing 'symbol'")
        # Base58 has no 0/O/I/l; length is 32-44 chars for a Solana pubkey.
        if not 32 <= len(self.mint) <= 44:
            raise ConfigError(f"{self.symbol}: {self.mint!r} is not a plausible Solana mint")
        if not 0 <= self.decimals <= 18:
            raise ConfigError(f"{self.symbol}: decimals must be in [0, 18]")


@dataclass(frozen=True)
class Config:
    """Top-level scanner configuration.

    All lamport-denominated fields are integers; all *_pct fields are fractions
    (0.001 == 10 bps), never percentages.
    """

    tokens: tuple[TokenConfig, ...]
    #: Notional per attempt, in SOL. Also the size every quote is priced at,
    #: since AMM edge is size-dependent and quoting a different size lies.
    trade_size_sol: float = 0.1
    #: Minimum net edge, as a fraction of notional, before a cycle is recorded.
    min_profit_pct: float = 0.003
    #: Slippage tolerance sent to Jupiter, in basis points.
    slippage_bps: int = 50
    #: Priority fee budgeted per transaction. Two transactions per cycle.
    priority_fee_lamports: int = 100_000
    #: Jito (or equivalent) bundle tip budgeted per cycle attempt.
    tip_lamports: int = 0
    #: Fraction of attempts assumed to land. Failed sends still burn fees, so
    #: the detector charges expected cost at this rate. 1.0 disables the model.
    landing_rate: float = 1.0
    jupiter_base_url: str = "https://lite-api.jup.ag/swap/v1"
    #: Seconds between scans in ``run`` mode.
    poll_interval: float = 3.0
    request_timeout: float = 8.0
    #: Refuse to submit anything on-chain unless explicitly flipped off.
    dry_run: bool = True
    #: Hard ceiling on live size per attempt, independent of trade_size_sol.
    max_live_trade_size_sol: float = 0.25
    #: Session stops once cumulative PnL in SOL drops below the negative of this.
    max_session_loss_sol: float = 0.05
    #: Env var holding the path to the signing keypair. Live mode only.
    keypair_path_env: str = "SOLANA_KEYPAIR_PATH"
    rpc_url_env: str = "SOLANA_RPC_URL"
    ledger_path: str = "arb_ledger.jsonl"
    #: Extra query params forwarded to the Jupiter quote endpoint.
    quote_params: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tokens:
            raise ConfigError("at least one token is required to form a cycle")
        mints = [t.mint for t in self.tokens]
        dupes = {m for m in mints if mints.count(m) > 1}
        if dupes:
            raise ConfigError(f"duplicate token mints: {sorted(dupes)}")
        if WRAPPED_SOL_MINT in mints:
            raise ConfigError("wrapped SOL is the cycle's base asset; remove it from 'tokens'")
        if self.trade_size_sol <= 0:
            raise ConfigError("trade_size_sol must be > 0")
        if self.min_profit_pct <= 0:
            raise ConfigError("min_profit_pct must be > 0; a zero threshold trades on noise")
        if not 0 <= self.slippage_bps <= 10_000:
            raise ConfigError("slippage_bps must be in [0, 10000]")
        if self.priority_fee_lamports < 0 or self.tip_lamports < 0:
            raise ConfigError("fee and tip budgets must be >= 0")
        if not 0 < self.landing_rate <= 1:
            raise ConfigError("landing_rate must be in (0, 1]")
        if self.poll_interval <= 0:
            raise ConfigError("poll_interval must be > 0")
        if self.request_timeout <= 0:
            raise ConfigError("request_timeout must be > 0")
        if self.max_live_trade_size_sol <= 0:
            raise ConfigError("max_live_trade_size_sol must be > 0")
        if self.max_session_loss_sol <= 0:
            raise ConfigError("max_session_loss_sol must be > 0")

    @property
    def trade_size_lamports(self) -> int:
        return int(round(self.trade_size_sol * LAMPORTS_PER_SOL))

    @property
    def cycle_fee_lamports(self) -> int:
        """Expected lamports burned per cycle attempt.

        A cycle is two swaps, each paying a signature fee and a priority fee,
        plus one optional bundle tip. When ``landing_rate`` is below 1 the cost
        is grossed up: fees are paid on attempts that never land, so a
        successful cycle has to carry the failed ones.
        """
        per_attempt = 2 * (BASE_SIGNATURE_FEE_LAMPORTS + self.priority_fee_lamports)
        return int(round((per_attempt + self.tip_lamports) / self.landing_rate))

    def with_overrides(self, **kwargs: Any) -> "Config":
        """Return a copy with the given fields replaced (validation re-runs)."""
        return replace(self, **{k: v for k, v in kwargs.items() if v is not None})


def _parse(text: str, path: Path) -> Mapping[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError:
            raise ConfigError(
                f"{path}: not valid JSON ({exc}); install PyYAML to use YAML configs"
            ) from exc
        loaded = yaml.safe_load(text)
        if not isinstance(loaded, Mapping):
            raise ConfigError(f"{path}: top level must be a mapping")
        return loaded


def from_mapping(raw: Mapping[str, Any]) -> Config:
    """Build a :class:`Config` from an already-parsed mapping."""
    unknown = set(raw) - set(Config.__dataclass_fields__)
    if unknown:
        raise ConfigError(f"unknown config keys: {sorted(unknown)}")

    raw_tokens = raw.get("tokens")
    if not isinstance(raw_tokens, (list, tuple)):
        raise ConfigError("'tokens' must be a list")
    tokens = []
    for entry in raw_tokens:
        if not isinstance(entry, Mapping):
            raise ConfigError("each token entry must be a mapping")
        bad = set(entry) - set(TokenConfig.__dataclass_fields__)
        if bad:
            raise ConfigError(f"unknown token keys: {sorted(bad)}")
        tokens.append(TokenConfig(**entry))

    scalars = {k: v for k, v in raw.items() if k != "tokens"}
    return Config(tokens=tuple(tokens), **scalars)


def load_config(path: str | Path) -> Config:
    """Load and validate a config file."""
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    return from_mapping(_parse(path.read_text(), path))
