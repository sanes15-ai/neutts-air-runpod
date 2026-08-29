import unittest

from arbitrage_bot.config import LAMPORTS_PER_SOL, TokenConfig, from_mapping
from arbitrage_bot.detector import evaluate_cycle, scan
from arbitrage_bot.jupiter import JupiterClient, QuoteError

USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
TOKEN = TokenConfig(symbol="USDC", mint=USDC, decimals=6)


class ScriptedTransport:
    """Returns a payload per call, in order; records the requested amounts."""

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.amounts = []

    def __call__(self, url, timeout):
        import urllib.parse

        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.amounts.append(int(query["amount"][0]))
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return payload


def quote_payload(out_amount, label="Orca"):
    return {"outAmount": str(out_amount), "routePlan": [{"swapInfo": {"label": label}}]}


def client_for(payloads):
    transport = ScriptedTransport(payloads)
    return JupiterClient("https://example.test", transport=transport), transport


class TestEvaluateCycle(unittest.TestCase):
    def test_second_leg_is_sized_by_first_leg_output(self):
        client, transport = client_for([quote_payload(20_000_000), quote_payload(100_000_000)])
        evaluate_cycle(client, TOKEN, 100_000_000, 0)
        # First leg quotes the notional; second quotes exactly what came back.
        self.assertEqual(transport.amounts, [100_000_000, 20_000_000])

    def test_profitable_cycle_nets_out_fees(self):
        size = 100_000_000
        client, _ = client_for([quote_payload(20_000_000), quote_payload(101_000_000)])
        opp = evaluate_cycle(client, TOKEN, size, 210_000)
        self.assertEqual(opp.gross_out_lamports, 101_000_000)
        self.assertEqual(opp.net_lamports, 1_000_000 - 210_000)
        self.assertAlmostEqual(opp.gross_pct, 0.01)
        self.assertAlmostEqual(opp.net_pct, 790_000 / size)
        self.assertTrue(opp.is_profitable(0.005))

    def test_gross_win_can_still_be_a_net_loss(self):
        """The whole point of the fee model: a 0.01% gap does not pay for itself."""
        size = 100_000_000
        client, _ = client_for([quote_payload(20_000_000), quote_payload(size + 10_000)])
        opp = evaluate_cycle(client, TOKEN, size, 210_000)
        self.assertGreater(opp.gross_pct, 0)
        self.assertLess(opp.net_lamports, 0)
        self.assertFalse(opp.is_profitable(0.0))

    def test_edge_below_threshold_is_not_profitable(self):
        size = 100_000_000
        client, _ = client_for([quote_payload(20_000_000), quote_payload(size + 300_000)])
        opp = evaluate_cycle(client, TOKEN, size, 0)
        self.assertAlmostEqual(opp.net_pct, 0.003)
        self.assertTrue(opp.is_profitable(0.003))
        self.assertFalse(opp.is_profitable(0.004))

    def test_round_trip_loss_is_the_common_case(self):
        size = 100_000_000
        client, _ = client_for([quote_payload(20_000_000), quote_payload(99_940_000)])
        opp = evaluate_cycle(client, TOKEN, size, 210_000)
        self.assertLess(opp.net_pct, 0)
        self.assertFalse(opp.is_profitable(0.001))

    def test_legs_carry_routes(self):
        client, _ = client_for(
            [quote_payload(20_000_000, "Orca"), quote_payload(100_500_000, "Raydium")]
        )
        opp = evaluate_cycle(client, TOKEN, 100_000_000, 0)
        self.assertEqual([leg.route for leg in opp.legs], ["Orca", "Raydium"])

    def test_to_dict_is_json_serializable(self):
        import json

        client, _ = client_for([quote_payload(20_000_000), quote_payload(100_500_000)])
        opp = evaluate_cycle(client, TOKEN, 100_000_000, 1_000, timestamp=1.5)
        payload = json.loads(json.dumps(opp.to_dict()))
        self.assertEqual(payload["symbol"], "USDC")
        self.assertEqual(len(payload["legs"]), 2)

    def test_net_sol_conversion(self):
        client, _ = client_for([quote_payload(20_000_000), quote_payload(101_000_000)])
        opp = evaluate_cycle(client, TOKEN, 100_000_000, 0)
        self.assertAlmostEqual(opp.net_sol, 1_000_000 / LAMPORTS_PER_SOL)

    def test_describe_mentions_both_symbols(self):
        client, _ = client_for([quote_payload(20_000_000), quote_payload(101_000_000)])
        self.assertIn("SOL->USDC->SOL", evaluate_cycle(client, TOKEN, 100_000_000, 0).describe())


class TestScan(unittest.TestCase):
    def config(self, **overrides):
        raw = {
            "tokens": [
                {"symbol": "USDC", "mint": USDC, "decimals": 6},
                {"symbol": "USDT", "mint": USDT, "decimals": 6},
            ],
            "trade_size_sol": 0.1,
        }
        raw.update(overrides)
        return from_mapping(raw)

    def test_yields_one_result_per_token(self):
        client, _ = client_for(
            [
                quote_payload(20_000_000),
                quote_payload(101_000_000),
                quote_payload(20_000_000),
                quote_payload(99_000_000),
            ]
        )
        results = list(scan(client, self.config()))
        self.assertEqual([o.symbol for o in results], ["USDC", "USDT"])

    def test_unpriceable_token_is_skipped_not_fatal(self):
        client, _ = client_for(
            [
                QuoteError("no route"),
                quote_payload(20_000_000),
                quote_payload(101_000_000),
            ]
        )
        with self.assertLogs("arbitrage_bot.detector", level="WARNING"):
            results = list(scan(client, self.config()))
        self.assertEqual([o.symbol for o in results], ["USDT"])

    def test_scan_uses_configured_size_and_fee(self):
        config = self.config(trade_size_sol=0.2, priority_fee_lamports=50_000, tip_lamports=0)
        client, transport = client_for([quote_payload(20_000_000), quote_payload(201_000_000)])
        opp = next(scan(client, config, tokens=config.tokens[:1]))
        self.assertEqual(transport.amounts[0], 200_000_000)
        self.assertEqual(opp.fee_lamports, config.cycle_fee_lamports)


if __name__ == "__main__":
    unittest.main()
