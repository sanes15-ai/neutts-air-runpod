"""Round-trip arbitrage detection.

A *cycle* is SOL -> token -> SOL. Both legs are priced through the aggregator at
the exact size that would be traded, because AMM edge is size-dependent: a gap
that exists at 0.01 SOL routinely vanishes at 1 SOL.

The edge reported here is net of every cost the bot can know up front --
aggregator/AMM fees are already inside the quoted output amounts, and signature,
priority and tip costs are subtracted on top. It is still an *estimate*: the
quote is not a fill, and by the time a transaction lands the pool may have moved.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterator, Sequence

from .config import LAMPORTS_PER_SOL, WRAPPED_SOL_MINT, Config, TokenConfig
from .jupiter import JupiterClient, Quote, QuoteError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Leg:
    """One priced hop of a cycle, flattened for logging."""

    input_mint: str
    output_mint: str
    in_amount: int
    out_amount: int
    route: str
    price_impact_pct: float

    @classmethod
    def from_quote(cls, quote: Quote) -> "Leg":
        return cls(
            input_mint=quote.input_mint,
            output_mint=quote.output_mint,
            in_amount=quote.in_amount,
            out_amount=quote.out_amount,
            route=quote.route,
            price_impact_pct=quote.price_impact_pct,
        )


@dataclass(frozen=True)
class Opportunity:
    """A completed round-trip evaluation, profitable or not."""

    symbol: str
    mint: str
    size_lamports: int
    #: Lamports returned by the second leg, before subtracting fees.
    gross_out_lamports: int
    fee_lamports: int
    legs: tuple[Leg, ...]
    timestamp: float

    @property
    def net_lamports(self) -> int:
        """Lamports gained (or lost) after all known costs."""
        return self.gross_out_lamports - self.size_lamports - self.fee_lamports

    @property
    def net_pct(self) -> float:
        """Net edge as a fraction of notional."""
        return self.net_lamports / self.size_lamports

    @property
    def gross_pct(self) -> float:
        """Edge before transaction costs -- useful for spotting fee-bound setups."""
        return (self.gross_out_lamports - self.size_lamports) / self.size_lamports

    @property
    def net_sol(self) -> float:
        return self.net_lamports / LAMPORTS_PER_SOL

    def is_profitable(self, min_profit_pct: float) -> bool:
        return self.net_lamports > 0 and self.net_pct >= min_profit_pct

    def describe(self) -> str:
        return (
            f"SOL->{self.symbol}->SOL  size={self.size_lamports / LAMPORTS_PER_SOL:.4f} SOL  "
            f"gross={self.gross_pct * 100:+.3f}%  net={self.net_pct * 100:+.3f}%  "
            f"({self.net_sol:+.6f} SOL)  via {' | '.join(leg.route for leg in self.legs)}"
        )

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "mint": self.mint,
            "size_lamports": self.size_lamports,
            "gross_out_lamports": self.gross_out_lamports,
            "fee_lamports": self.fee_lamports,
            "net_lamports": self.net_lamports,
            "net_pct": self.net_pct,
            "gross_pct": self.gross_pct,
            "legs": [leg.__dict__ for leg in self.legs],
        }


def evaluate_cycle(
    client: JupiterClient,
    token: TokenConfig,
    size_lamports: int,
    fee_lamports: int,
    *,
    timestamp: float = 0.0,
) -> Opportunity:
    """Price SOL -> token -> SOL and return the resulting edge.

    Raises :class:`~arbitrage_bot.jupiter.QuoteError` if either leg cannot be
    priced; callers are expected to treat that as "skip this token this tick",
    not as a fatal error.
    """
    outbound = client.quote(WRAPPED_SOL_MINT, token.mint, size_lamports)
    # The second leg must be sized by what the first leg actually returns --
    # quoting a round number here would price a trade that cannot be executed.
    inbound = client.quote(token.mint, WRAPPED_SOL_MINT, outbound.out_amount)
    return Opportunity(
        symbol=token.symbol,
        mint=token.mint,
        size_lamports=size_lamports,
        gross_out_lamports=inbound.out_amount,
        fee_lamports=fee_lamports,
        legs=(Leg.from_quote(outbound), Leg.from_quote(inbound)),
        timestamp=timestamp,
    )


def scan(
    client: JupiterClient,
    config: Config,
    *,
    tokens: Sequence[TokenConfig] | None = None,
    timestamp: float = 0.0,
) -> Iterator[Opportunity]:
    """Evaluate every configured token once, yielding each result.

    Unpriceable tokens are logged and skipped so one illiquid mint cannot stall
    the loop. Filtering to profitable cycles is the caller's job -- losing
    evaluations are worth recording, since they are what tells you whether the
    strategy is merely fee-bound or genuinely absent.
    """
    for token in tokens if tokens is not None else config.tokens:
        try:
            yield evaluate_cycle(
                client,
                token,
                config.trade_size_lamports,
                config.cycle_fee_lamports,
                timestamp=timestamp,
            )
        except QuoteError as exc:
            log.warning("skipping %s: %s", token.symbol, exc)
