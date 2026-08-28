"""Execution back-ends.

:class:`PaperExecutor` books the detector's own estimate as a fill and touches
nothing on-chain. :class:`LiveExecutor` is the real thing and is deliberately
hard to reach: it refuses to construct unless ``dry_run`` is off, the size is
under the hard cap, and a keypair is present.

Both share :class:`RiskGuard`, so the session loss limit applies to paper runs
too -- a paper run that trips the limit is telling you the live one would have.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from .config import LAMPORTS_PER_SOL, Config
from .detector import Opportunity

log = logging.getLogger(__name__)


class RiskLimitExceeded(RuntimeError):
    """Raised when a trade would breach a configured safety limit."""


@dataclass
class Fill:
    """The outcome of attempting one cycle."""

    opportunity: Opportunity
    net_lamports: int
    mode: str
    signature: str | None = None

    def to_dict(self) -> dict:
        return {
            **self.opportunity.to_dict(),
            "net_lamports": self.net_lamports,
            "mode": self.mode,
            "signature": self.signature,
        }


class RiskGuard:
    """Enforces per-trade size and cumulative session loss limits."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.cumulative_lamports = 0

    @property
    def cumulative_sol(self) -> float:
        return self.cumulative_lamports / LAMPORTS_PER_SOL

    def check(self, opportunity: Opportunity) -> None:
        max_size = int(round(self.config.max_live_trade_size_sol * LAMPORTS_PER_SOL))
        if opportunity.size_lamports > max_size:
            raise RiskLimitExceeded(
                f"trade size {opportunity.size_lamports} lamports exceeds hard cap {max_size}"
            )
        floor = -int(round(self.config.max_session_loss_sol * LAMPORTS_PER_SOL))
        if self.cumulative_lamports <= floor:
            raise RiskLimitExceeded(
                f"session loss limit reached ({self.cumulative_sol:.6f} SOL); halting"
            )

    def book(self, net_lamports: int) -> None:
        self.cumulative_lamports += net_lamports


class PaperExecutor:
    """Books the estimated edge without sending anything on-chain.

    The recorded PnL is the detector's estimate, so a paper run is an upper
    bound on live performance: it assumes every attempt lands at the quoted
    price with no competing bot in front of it. Treat a paper edge that barely
    clears the threshold as a loss.
    """

    mode = "paper"

    def __init__(self, config: Config) -> None:
        self.config = config
        self.guard = RiskGuard(config)

    def execute(self, opportunity: Opportunity) -> Fill:
        self.guard.check(opportunity)
        fill = Fill(opportunity=opportunity, net_lamports=opportunity.net_lamports, mode=self.mode)
        self.guard.book(fill.net_lamports)
        log.info("paper fill: %s", opportunity.describe())
        return fill


class LiveExecutor:
    """Submits real swaps. Constructing one is an explicit, guarded act.

    Building and signing the two swap transactions needs ``solders`` and
    ``solana`` installed and a funded keypair; :meth:`execute` raises
    :class:`NotImplementedError` until :meth:`_submit` is filled in, so an
    accidental live run cannot silently move funds.
    """

    mode = "live"

    def __init__(self, config: Config) -> None:
        if config.dry_run:
            raise RiskLimitExceeded("refusing to build a live executor while dry_run is set")
        if config.trade_size_sol > config.max_live_trade_size_sol:
            raise RiskLimitExceeded(
                f"trade_size_sol {config.trade_size_sol} exceeds "
                f"max_live_trade_size_sol {config.max_live_trade_size_sol}"
            )
        keypair_path = os.environ.get(config.keypair_path_env)
        if not keypair_path:
            raise RiskLimitExceeded(f"{config.keypair_path_env} is unset; cannot sign live swaps")
        if not Path(keypair_path).is_file():
            raise RiskLimitExceeded(f"keypair file not found: {keypair_path}")
        self.config = config
        self.keypair_path = keypair_path
        self.rpc_url = os.environ.get(config.rpc_url_env, "https://api.mainnet-beta.solana.com")
        self.guard = RiskGuard(config)

    def execute(self, opportunity: Opportunity) -> Fill:
        self.guard.check(opportunity)
        signature, net_lamports = self._submit(opportunity)
        self.guard.book(net_lamports)
        return Fill(
            opportunity=opportunity,
            net_lamports=net_lamports,
            mode=self.mode,
            signature=signature,
        )

    def _submit(self, opportunity: Opportunity) -> tuple[str, int]:
        """Build, sign and send both swap legs; return (signature, realized PnL).

        Left unimplemented on purpose. Wiring this up means requesting
        ``/swap`` transactions from Jupiter for each leg, signing with the
        configured keypair, sending with a priority fee, and measuring the
        realized lamport delta from the confirmed transaction rather than
        trusting the quote. Do not implement it until a paper run over several
        days shows an edge that survives the fee model.
        """
        raise NotImplementedError(
            "live submission is not wired up; run in paper mode until the edge is proven"
        )


def build_executor(config: Config) -> PaperExecutor | LiveExecutor:
    """Pick an executor based on ``dry_run``."""
    return PaperExecutor(config) if config.dry_run else LiveExecutor(config)
