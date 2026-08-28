import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arbitrage_bot.config import LAMPORTS_PER_SOL, from_mapping
from arbitrage_bot.detector import Leg, Opportunity
from arbitrage_bot.executor import (
    LiveExecutor,
    PaperExecutor,
    RiskLimitExceeded,
    build_executor,
)

USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def config(**overrides):
    raw = {"tokens": [{"symbol": "USDC", "mint": USDC, "decimals": 6}]}
    raw.update(overrides)
    return from_mapping(raw)


def opportunity(size_lamports=100_000_000, gross_out=101_000_000, fee=210_000):
    leg = Leg(USDC, USDC, size_lamports, gross_out, "Orca", 0.0)
    return Opportunity(
        symbol="USDC",
        mint=USDC,
        size_lamports=size_lamports,
        gross_out_lamports=gross_out,
        fee_lamports=fee,
        legs=(leg, leg),
        timestamp=0.0,
    )


class TestPaperExecutor(unittest.TestCase):
    def test_books_the_estimated_edge(self):
        executor = PaperExecutor(config())
        fill = executor.execute(opportunity())
        self.assertEqual(fill.mode, "paper")
        self.assertEqual(fill.net_lamports, 790_000)
        self.assertIsNone(fill.signature)

    def test_pnl_accumulates_across_fills(self):
        executor = PaperExecutor(config())
        executor.execute(opportunity())
        executor.execute(opportunity())
        self.assertEqual(executor.guard.cumulative_lamports, 1_580_000)

    def test_size_over_hard_cap_is_refused(self):
        executor = PaperExecutor(config(max_live_trade_size_sol=0.05))
        with self.assertRaises(RiskLimitExceeded) as ctx:
            executor.execute(opportunity(size_lamports=100_000_000))
        self.assertIn("hard cap", str(ctx.exception))

    def test_session_loss_limit_halts_further_trading(self):
        executor = PaperExecutor(config(max_session_loss_sol=0.001))
        losing = opportunity(gross_out=98_000_000)
        executor.execute(losing)  # first loss is allowed, it is what breaches the limit
        with self.assertRaises(RiskLimitExceeded) as ctx:
            executor.execute(losing)
        self.assertIn("session loss limit", str(ctx.exception))

    def test_fill_dict_carries_mode_and_net(self):
        fill = PaperExecutor(config()).execute(opportunity())
        payload = fill.to_dict()
        self.assertEqual(payload["mode"], "paper")
        self.assertEqual(payload["net_lamports"], 790_000)


class TestLiveExecutor(unittest.TestCase):
    def test_refuses_to_construct_in_dry_run(self):
        with self.assertRaises(RiskLimitExceeded) as ctx:
            LiveExecutor(config(dry_run=True))
        self.assertIn("dry_run", str(ctx.exception))

    def test_refuses_size_above_live_cap(self):
        with mock.patch.dict(os.environ, {"SOLANA_KEYPAIR_PATH": "/tmp/nope"}):
            with self.assertRaises(RiskLimitExceeded):
                LiveExecutor(config(dry_run=False, trade_size_sol=1.0, max_live_trade_size_sol=0.25))

    def test_requires_keypair_env(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RiskLimitExceeded) as ctx:
                LiveExecutor(config(dry_run=False, trade_size_sol=0.1))
            self.assertIn("SOLANA_KEYPAIR_PATH", str(ctx.exception))

    def test_requires_keypair_file_to_exist(self):
        with mock.patch.dict(os.environ, {"SOLANA_KEYPAIR_PATH": "/nonexistent/key.json"}):
            with self.assertRaises(RiskLimitExceeded) as ctx:
                LiveExecutor(config(dry_run=False, trade_size_sol=0.1))
            self.assertIn("not found", str(ctx.exception))

    def test_submission_is_not_wired_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            key = Path(tmp) / "key.json"
            key.write_text("[]")
            with mock.patch.dict(os.environ, {"SOLANA_KEYPAIR_PATH": str(key)}):
                executor = LiveExecutor(config(dry_run=False, trade_size_sol=0.1))
                self.assertEqual(executor.mode, "live")
                with self.assertRaises(NotImplementedError):
                    executor.execute(opportunity())


class TestBuildExecutor(unittest.TestCase):
    def test_dry_run_yields_paper(self):
        self.assertIsInstance(build_executor(config()), PaperExecutor)

    def test_live_flag_yields_live(self):
        with tempfile.TemporaryDirectory() as tmp:
            key = Path(tmp) / "key.json"
            key.write_text("[]")
            with mock.patch.dict(os.environ, {"SOLANA_KEYPAIR_PATH": str(key)}):
                self.assertIsInstance(
                    build_executor(config(dry_run=False, trade_size_sol=0.1)), LiveExecutor
                )


if __name__ == "__main__":
    unittest.main()
