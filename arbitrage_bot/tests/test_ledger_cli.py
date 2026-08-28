import io
import json
import tempfile
import unittest
import urllib.parse
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from arbitrage_bot import cli
from arbitrage_bot.ledger import Ledger

USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"


class TestLedger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "nested" / "ledger.jsonl"

    def test_creates_parent_directory(self):
        Ledger(self.path)
        self.assertTrue(self.path.parent.is_dir())

    def test_records_are_one_json_object_per_line(self):
        ledger = Ledger(self.path)
        ledger.record("scan", {"symbol": "USDC"})
        ledger.record("scan", {"symbol": "USDT"})
        lines = self.path.read_text().strip().split("\n")
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["kind"], "scan")

    def test_fills_accumulate_pnl(self):
        ledger = Ledger(self.path)
        ledger.record("fill", {"net_lamports": 500_000})
        ledger.record("fill", {"net_lamports": -200_000})
        self.assertEqual(ledger.realized_lamports, 300_000)
        self.assertEqual(ledger.fills, 2)

    def test_summary_counts_wins_and_hit_rate(self):
        ledger = Ledger(self.path)
        ledger.record("scan", {})
        ledger.record("fill", {"net_lamports": 1_000_000})
        ledger.record("fill", {"net_lamports": -1_000_000})
        summary = ledger.summary()
        self.assertEqual(summary["scans"], 1)
        self.assertEqual(summary["fills"], 2)
        self.assertEqual(summary["wins"], 1)
        self.assertEqual(summary["net_lamports"], 0)
        self.assertAlmostEqual(summary["hit_rate"], 0.5)

    def test_truncated_tail_line_is_skipped(self):
        ledger = Ledger(self.path)
        ledger.record("fill", {"net_lamports": 1})
        with self.path.open("a") as handle:
            handle.write('{"kind": "fill", "net_l')
        self.assertEqual(ledger.summary()["fills"], 1)

    def test_summary_of_empty_ledger(self):
        self.assertEqual(Ledger(self.path).summary()["hit_rate"], 0.0)


def quote_payload(out_amount):
    return {"outAmount": str(out_amount), "routePlan": [{"swapInfo": {"label": "Orca"}}]}


class CyclingTransport:
    """Prices every SOL->token leg the same and the return leg at a fixed edge."""

    def __init__(self, return_lamports):
        self.return_lamports = return_lamports
        self.calls = 0

    def __call__(self, url, timeout):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.calls += 1
        is_outbound = query["inputMint"][0].startswith("So1")
        return quote_payload(20_000_000 if is_outbound else self.return_lamports)


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.ledger_path = root / "ledger.jsonl"
        self.config_path = root / "config.json"
        self.config_path.write_text(
            json.dumps(
                {
                    "tokens": [{"symbol": "USDC", "mint": USDC, "decimals": 6}],
                    "trade_size_sol": 0.1,
                    "min_profit_pct": 0.003,
                    "priority_fee_lamports": 100_000,
                    "poll_interval": 0.01,
                    "ledger_path": str(self.ledger_path),
                }
            )
        )

    def run_cli(self, argv, return_lamports):
        transport = CyclingTransport(return_lamports)
        real_client = cli.JupiterClient

        def patched(base_url, **kwargs):
            kwargs.pop("transport", None)
            return real_client(base_url, transport=transport, **kwargs)

        with mock.patch.object(cli, "JupiterClient", patched):
            with self.assertLogs("arbitrage_bot", level="DEBUG"):
                return cli.main(argv)

    def test_scan_records_a_losing_cycle_without_filling(self):
        code = self.run_cli(["scan", "--config", str(self.config_path)], 99_000_000)
        self.assertEqual(code, 0)
        summary = Ledger(self.ledger_path).summary()
        self.assertEqual(summary["scans"], 1)
        self.assertEqual(summary["fills"], 0)

    def test_scan_fills_a_profitable_cycle_in_paper_mode(self):
        code = self.run_cli(["scan", "--config", str(self.config_path)], 101_000_000)
        self.assertEqual(code, 0)
        summary = Ledger(self.ledger_path).summary()
        self.assertEqual(summary["fills"], 1)
        self.assertGreater(summary["net_lamports"], 0)

    def test_min_profit_override_suppresses_marginal_fill(self):
        code = self.run_cli(
            ["scan", "--config", str(self.config_path), "--min-profit-pct", "0.5"], 101_000_000
        )
        self.assertEqual(code, 0)
        self.assertEqual(Ledger(self.ledger_path).summary()["fills"], 0)

    def test_run_stops_after_requested_iterations(self):
        code = self.run_cli(
            ["run", "--config", str(self.config_path), "--iterations", "3"], 99_000_000
        )
        self.assertEqual(code, 0)
        self.assertEqual(Ledger(self.ledger_path).summary()["scans"], 3)

    def test_run_halts_when_a_risk_limit_trips(self):
        # Notional above the hard per-trade cap: the guard refuses the fill and
        # the loop exits non-zero rather than quietly skipping it.
        raw = json.loads(self.config_path.read_text())
        raw["max_live_trade_size_sol"] = 0.01
        self.config_path.write_text(json.dumps(raw))
        code = self.run_cli(
            ["run", "--config", str(self.config_path), "--iterations", "50"], 101_000_000
        )
        self.assertEqual(code, 1)
        kinds = [e["kind"] for e in Ledger(self.ledger_path).read()]
        self.assertIn("error", kinds)

    def test_report_prints_summary(self):
        ledger = Ledger(self.ledger_path)
        ledger.record("fill", {"net_lamports": 1_000_000})
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cli.main(["report", "--config", str(self.config_path)])
        self.assertEqual(code, 0)
        self.assertIn("fills=1", buffer.getvalue())

    def test_bad_config_exits_two(self):
        bad = Path(self.tmp.name) / "bad.json"
        bad.write_text(json.dumps({"tokens": []}))
        with self.assertLogs("arbitrage_bot", level="ERROR"):
            self.assertEqual(cli.main(["scan", "--config", str(bad)]), 2)

    def test_live_flag_without_keypair_exits_two(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertLogs("arbitrage_bot", level="ERROR"):
                code = cli.main(["scan", "--config", str(self.config_path), "--live"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
