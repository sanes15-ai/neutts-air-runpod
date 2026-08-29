"""Entry point for the live demo-trading loop.

    python -m trading_bot.run_mt5 --symbol EURUSD --risk 0.10

Run this on the Windows machine where your MT5 terminal is logged into the
Exness demo account, with Algo Trading enabled.
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
from pathlib import Path

from .mt5_bot import BotConfig, BotState, SafetyError, connect, step

log = logging.getLogger("trading_bot")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="trading_bot.run_mt5")
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--timeframe", default="D1", choices=["M5", "M15", "M30", "H1", "H4", "D1"])
    p.add_argument("--risk", type=float, default=0.10, help="fraction of equity risked per trade")
    p.add_argument("--poll", type=float, default=60.0, help="seconds between decision cycles")
    p.add_argument("--strategies", nargs="*", default=None)
    p.add_argument("--log-path", default="mt5_trades.jsonl")
    p.add_argument("--once", action="store_true", help="run a single cycle and exit")
    p.add_argument(
        "--i-understand-live",
        action="store_true",
        help="permit trading a NON-demo account. Do not use this.",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    config = BotConfig(
        symbol=args.symbol,
        timeframe=args.timeframe,
        risk_per_trade=args.risk,
        poll_seconds=args.poll,
        allow_live=args.i_understand_live,
        log_path=args.log_path,
    )
    if args.strategies:
        config.strategies = tuple(args.strategies)
    if not 0 < config.risk_per_trade <= 0.25:
        log.error("risk must be in (0, 0.25]; %.3f refused", config.risk_per_trade)
        return 2

    try:
        mt5, info = connect(config)
    except SafetyError as exc:
        log.error("cannot start: %s", exc)
        return 2

    state = BotState(start_equity=info.equity, day_start_equity=info.equity)
    ledger = Path(config.log_path)
    stopping = False

    def _stop(*_):
        nonlocal stopping
        stopping = True
        log.info("stop requested; finishing cycle")

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    log.info(
        "trading %s %s | strategies=%s | risk=%.0f%% | floor=%.0f%% | daily limit=%.0f%%",
        config.symbol, config.timeframe, ",".join(config.strategies),
        config.risk_per_trade * 100, config.equity_floor * 100, config.daily_loss_limit * 100,
    )

    exit_code = 0
    while not stopping:
        try:
            record = step(mt5, config, state)
            with ledger.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=str) + "\n")
            if record["action"] != "hold":
                log.info("%s | target=%+d | equity=%.2f", record["action"], record["target"],
                         record["equity"])
        except SafetyError as exc:
            log.error("HALTED: %s", exc)
            exit_code = 1
            break
        except Exception as exc:  # noqa: BLE001 - a loop that dies silently is worse
            log.exception("cycle failed: %s", exc)
        if args.once:
            break
        deadline = time.monotonic() + config.poll_seconds
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))

    mt5.shutdown()
    log.info("stopped after %d orders", state.orders_sent)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
