import json
import os
import tempfile
import unittest
from pathlib import Path

from arbitrage_bot.config import (
    BASE_SIGNATURE_FEE_LAMPORTS,
    WRAPPED_SOL_MINT,
    ConfigError,
    from_mapping,
    load_config,
)

USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"


def base(**overrides):
    raw = {"tokens": [{"symbol": "USDC", "mint": USDC, "decimals": 6}]}
    raw.update(overrides)
    return raw


class TestConfig(unittest.TestCase):
    def test_minimal_config_uses_defaults(self):
        config = from_mapping(base())
        self.assertTrue(config.dry_run)
        self.assertEqual(config.tokens[0].symbol, "USDC")

    def test_trade_size_converts_to_lamports(self):
        self.assertEqual(from_mapping(base(trade_size_sol=0.25)).trade_size_lamports, 250_000_000)

    def test_cycle_fee_counts_two_signatures_and_two_priority_fees(self):
        config = from_mapping(base(priority_fee_lamports=100_000, tip_lamports=7_000))
        expected = 2 * (BASE_SIGNATURE_FEE_LAMPORTS + 100_000) + 7_000
        self.assertEqual(config.cycle_fee_lamports, expected)

    def test_landing_rate_grosses_up_expected_fees(self):
        full = from_mapping(base(landing_rate=1.0)).cycle_fee_lamports
        half = from_mapping(base(landing_rate=0.5)).cycle_fee_lamports
        self.assertEqual(half, full * 2)

    def test_rejects_empty_token_list(self):
        with self.assertRaises(ConfigError):
            from_mapping({"tokens": []})

    def test_rejects_duplicate_mints(self):
        with self.assertRaises(ConfigError):
            from_mapping({"tokens": [
                {"symbol": "A", "mint": USDC},
                {"symbol": "B", "mint": USDC},
            ]})

    def test_rejects_wrapped_sol_as_intermediate(self):
        with self.assertRaises(ConfigError) as ctx:
            from_mapping({"tokens": [{"symbol": "SOL", "mint": WRAPPED_SOL_MINT, "decimals": 9}]})
        self.assertIn("base asset", str(ctx.exception))

    def test_rejects_zero_profit_threshold(self):
        with self.assertRaises(ConfigError):
            from_mapping(base(min_profit_pct=0))

    def test_rejects_out_of_range_landing_rate(self):
        for bad in (0, -0.1, 1.5):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                from_mapping(base(landing_rate=bad))

    def test_rejects_implausible_mint(self):
        with self.assertRaises(ConfigError):
            from_mapping({"tokens": [{"symbol": "X", "mint": "tooshort"}]})

    def test_rejects_unknown_keys(self):
        with self.assertRaises(ConfigError):
            from_mapping(base(profit_multiplier=9000))

    def test_with_overrides_ignores_none_and_revalidates(self):
        config = from_mapping(base(trade_size_sol=0.1))
        self.assertEqual(config.with_overrides(trade_size_sol=None).trade_size_sol, 0.1)
        self.assertEqual(config.with_overrides(trade_size_sol=0.5).trade_size_sol, 0.5)
        with self.assertRaises(ConfigError):
            config.with_overrides(trade_size_sol=-1)

    def test_load_config_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text(json.dumps(base(trade_size_sol=0.2)))
            self.assertEqual(load_config(path).trade_size_sol, 0.2)

    def test_load_config_missing_file(self):
        with self.assertRaises(ConfigError):
            load_config("/nonexistent/nope.json")

    def test_example_config_is_valid(self):
        example = Path(__file__).resolve().parent.parent / "config.example.json"
        config = load_config(example)
        self.assertGreaterEqual(len(config.tokens), 2)
        self.assertTrue(config.dry_run)


if __name__ == "__main__":
    unittest.main()
