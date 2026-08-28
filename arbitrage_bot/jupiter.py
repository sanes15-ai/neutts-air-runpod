"""Minimal Jupiter aggregator client.

Uses ``urllib`` from the stdlib so the scanner has no install-time dependencies.
The transport is injectable, which is what lets the detector tests run against
recorded quotes instead of the network.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping

#: A transport takes a fully-formed URL and returns the decoded JSON body.
Transport = Callable[[str, float], Mapping[str, Any]]


class QuoteError(RuntimeError):
    """Raised when a quote cannot be obtained or cannot be understood."""


@dataclass(frozen=True)
class Quote:
    """One priced hop, as returned by the aggregator."""

    input_mint: str
    output_mint: str
    in_amount: int
    out_amount: int
    #: Aggregator's own estimate of price impact, as a fraction.
    price_impact_pct: float
    #: Human-readable route, e.g. "Orca -> Raydium".
    route: str
    #: Wall-clock time the quote was received, for staleness checks.
    received_at: float
    raw: Mapping[str, Any]


def _urlopen_transport(url: str, timeout: float) -> Mapping[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise QuoteError(f"quote HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise QuoteError(f"quote request failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise QuoteError(f"quote response was not JSON: {exc}") from exc


def _route_label(payload: Mapping[str, Any]) -> str:
    plan = payload.get("routePlan") or []
    labels = []
    for hop in plan:
        info = hop.get("swapInfo") if isinstance(hop, Mapping) else None
        if isinstance(info, Mapping) and info.get("label"):
            labels.append(str(info["label"]))
    return " -> ".join(labels) if labels else "unknown"


class JupiterClient:
    """Fetches swap quotes.

    Parameters
    ----------
    base_url:
        Jupiter swap API root, e.g. ``https://lite-api.jup.ag/swap/v1``.
    transport:
        Override for testing or for swapping in an authenticated HTTP client.
    """

    def __init__(
        self,
        base_url: str,
        *,
        slippage_bps: int = 50,
        timeout: float = 8.0,
        extra_params: Mapping[str, Any] | None = None,
        transport: Transport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.slippage_bps = slippage_bps
        self.timeout = timeout
        self.extra_params = dict(extra_params or {})
        self._transport = transport or _urlopen_transport
        self._clock = clock

    def quote(self, input_mint: str, output_mint: str, amount: int) -> Quote:
        """Price ``amount`` base units of ``input_mint`` into ``output_mint``."""
        if amount <= 0:
            raise QuoteError(f"quote amount must be positive, got {amount}")
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount),
            "slippageBps": str(self.slippage_bps),
            **self.extra_params,
        }
        url = f"{self.base_url}/quote?{urllib.parse.urlencode(params)}"
        payload = self._transport(url, self.timeout)
        if not isinstance(payload, Mapping):
            raise QuoteError("quote response was not a JSON object")
        if payload.get("error"):
            raise QuoteError(f"aggregator error: {payload['error']}")
        try:
            out_amount = int(payload["outAmount"])
            in_amount = int(payload.get("inAmount", amount))
        except (KeyError, TypeError, ValueError) as exc:
            raise QuoteError(f"quote response missing usable amounts: {payload}") from exc
        if out_amount <= 0:
            raise QuoteError("aggregator returned a non-positive output amount")
        try:
            impact = float(payload.get("priceImpactPct") or 0.0)
        except (TypeError, ValueError):
            impact = 0.0
        return Quote(
            input_mint=input_mint,
            output_mint=output_mint,
            in_amount=in_amount,
            out_amount=out_amount,
            price_impact_pct=impact,
            route=_route_label(payload),
            received_at=self._clock(),
            raw=payload,
        )
