"""Command line entry point.

    python -m arbitrage_bot scan   --config config.json
    python -m arbitrage_bot run    --config config.json
    python -m arbitrage_bot report --config config.json
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from typing import Sequence

from .config import LAMPORTS_PER_SOL, Config, ConfigError, load_config
from .detector import scan
from .executor import RiskLimitExceeded, build_executor
from .jupiter import JupiterClient
from .ledger import Ledger

log = logging.getLogger("arbitrage_bot")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arbitrage_bot",
        description="Solana round-trip arbitrage scanner (paper by default).",
    )
    parser.add_argument("command", choices=("scan", "run", "report"))
    parser.add_argument("--config", required=True, help="path to a JSON config file")
    parser.add_argument("--size", type=float, help="override trade size, in SOL")
    parser.add_argument(
        "--min-profit-pct",
        type=float,
        help="override the minimum net edge, as a fraction (0.003 == 0.3%%)",
    )
    parser.add_argument("--poll-interval", type=float, help="override seconds between scans")
    parser.add_argument("--ledger", help="override the ledger path")
    parser.add_argument(
        "--iterations", type=int, help="stop 'run' after this many passes (default: forever)"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="submit real swaps. Requires a funded keypair and a proven paper edge.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def _config_from_args(args: argparse.Namespace) -> Config:
    config = load_config(args.config)
    return config.with_overrides(
        trade_size_sol=args.size,
        min_profit_pct=args.min_profit_pct,
        poll_interval=args.poll_interval,
        ledger_path=args.ledger,
        dry_run=False if args.live else None,
    )


def _scan_once(client: JupiterClient, config: Config, ledger: Ledger, executor) -> int:
    """Run one pass. Returns the number of profitable cycles acted on."""
    acted = 0
    for opportunity in scan(client, config, timestamp=time.time()):
        ledger.record("scan", opportunity.to_dict())
        if not opportunity.is_profitable(config.min_profit_pct):
            log.debug("no edge: %s", opportunity.describe())
            continue
        log.info("OPPORTUNITY %s", opportunity.describe())
        try:
            fill = executor.execute(opportunity)
        except RiskLimitExceeded as exc:
            log.error("risk limit: %s", exc)
            ledger.record("error", {"reason": str(exc), "symbol": opportunity.symbol})
            raise
        except NotImplementedError as exc:
            log.error("execution unavailable: %s", exc)
            ledger.record("error", {"reason": str(exc), "symbol": opportunity.symbol})
            continue
        ledger.record("fill", fill.to_dict())
        acted += 1
    return acted


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        config = _config_from_args(args)
    except ConfigError as exc:
        log.error("config error: %s", exc)
        return 2

    ledger = Ledger(config.ledger_path)

    if args.command == "report":
        summary = ledger.summary()
        print(
            f"scans={summary['scans']} fills={summary['fills']} wins={summary['wins']} "
            f"hit_rate={summary['hit_rate'] * 100:.1f}% net={summary['net_sol']:+.6f} SOL"
        )
        return 0

    client = JupiterClient(
        config.jupiter_base_url,
        slippage_bps=config.slippage_bps,
        timeout=config.request_timeout,
        extra_params=config.quote_params,
    )

    try:
        executor = build_executor(config)
    except RiskLimitExceeded as exc:
        log.error("cannot start: %s", exc)
        return 2

    if executor.mode == "live":
        log.warning("LIVE MODE: real funds, max %.4f SOL per attempt", config.max_live_trade_size_sol)
    else:
        log.info(
            "paper mode: size=%.4f SOL, threshold=%.3f%%, budgeted fees=%d lamports/cycle",
            config.trade_size_sol,
            config.min_profit_pct * 100,
            config.cycle_fee_lamports,
        )

    if args.command == "scan":
        try:
            _scan_once(client, config, ledger, executor)
        except RiskLimitExceeded:
            return 1
        return 0

    stopping = False

    def _handle_signal(*_: object) -> None:
        nonlocal stopping
        stopping = True
        log.info("stop requested; finishing current pass")

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    passes = 0
    exit_code = 0
    while not stopping:
        try:
            _scan_once(client, config, ledger, executor)
        except RiskLimitExceeded:
            exit_code = 1
            break
        passes += 1
        if args.iterations is not None and passes >= args.iterations:
            break
        # Sleep in slices so a signal is honoured promptly.
        deadline = time.monotonic() + config.poll_interval
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))

    summary = ledger.summary()
    log.info(
        "done: %d passes, %d fills, net %+.6f SOL (%d lamports)",
        passes,
        summary["fills"],
        summary["net_sol"],
        summary["net_lamports"],
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
