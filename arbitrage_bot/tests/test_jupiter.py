import unittest
import urllib.parse

from arbitrage_bot.jupiter import JupiterClient, QuoteError


def fake_quote(out_amount, *, impact="0.0001", labels=("Orca", "Raydium")):
    return {
        "outAmount": str(out_amount),
        "priceImpactPct": impact,
        "routePlan": [{"swapInfo": {"label": label}} for label in labels],
    }


class RecordingTransport:
    """Captures requested URLs and replays canned payloads in order."""

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.urls = []

    def __call__(self, url, timeout):
        self.urls.append(url)
        if not self.payloads:
            raise AssertionError("transport called more times than payloads provided")
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return payload


class TestJupiterClient(unittest.TestCase):
    def client(self, payloads, **kwargs):
        self.transport = RecordingTransport(payloads)
        return JupiterClient(
            "https://example.test/swap/v1/", transport=self.transport, **kwargs
        )

    def test_builds_expected_query(self):
        client = self.client([fake_quote(123)], slippage_bps=25)
        client.quote("MintA" * 7, "MintB" * 7, 1_000)
        url = self.transport.urls[0]
        self.assertTrue(url.startswith("https://example.test/swap/v1/quote?"))
        params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertEqual(params["amount"], ["1000"])
        self.assertEqual(params["slippageBps"], ["25"])

    def test_trailing_slash_does_not_double(self):
        client = self.client([fake_quote(1)])
        client.quote("a" * 32, "b" * 32, 1)
        self.assertNotIn("//quote", self.transport.urls[0].replace("https://", ""))

    def test_extra_params_are_forwarded(self):
        client = self.client([fake_quote(1)], extra_params={"onlyDirectRoutes": "true"})
        client.quote("a" * 32, "b" * 32, 1)
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.transport.urls[0]).query)
        self.assertEqual(params["onlyDirectRoutes"], ["true"])

    def test_parses_amounts_impact_and_route(self):
        client = self.client([fake_quote(5_000, impact="0.0025")])
        quote = client.quote("a" * 32, "b" * 32, 1_000)
        self.assertEqual(quote.out_amount, 5_000)
        self.assertEqual(quote.in_amount, 1_000)
        self.assertAlmostEqual(quote.price_impact_pct, 0.0025)
        self.assertEqual(quote.route, "Orca -> Raydium")

    def test_unparseable_impact_defaults_to_zero(self):
        client = self.client([fake_quote(5_000, impact="n/a")])
        self.assertEqual(client.quote("a" * 32, "b" * 32, 1).price_impact_pct, 0.0)

    def test_missing_route_plan_is_labelled_unknown(self):
        client = self.client([{"outAmount": "7"}])
        self.assertEqual(client.quote("a" * 32, "b" * 32, 1).route, "unknown")

    def test_rejects_non_positive_amount(self):
        client = self.client([])
        with self.assertRaises(QuoteError):
            client.quote("a" * 32, "b" * 32, 0)

    def test_error_field_becomes_quote_error(self):
        client = self.client([{"error": "no route found"}])
        with self.assertRaises(QuoteError) as ctx:
            client.quote("a" * 32, "b" * 32, 1)
        self.assertIn("no route found", str(ctx.exception))

    def test_missing_out_amount_becomes_quote_error(self):
        client = self.client([{"routePlan": []}])
        with self.assertRaises(QuoteError):
            client.quote("a" * 32, "b" * 32, 1)

    def test_zero_out_amount_becomes_quote_error(self):
        client = self.client([fake_quote(0)])
        with self.assertRaises(QuoteError):
            client.quote("a" * 32, "b" * 32, 1)


if __name__ == "__main__":
    unittest.main()
