import unittest

import numpy as np
import pandas as pd

from trading_bot import backtest, indicators as ind, portfolio, validation as V
from trading_bot import strategies as S
from trading_bot.mt5_bot import BotConfig, desired_position


def make_df(closes, spread_hl=0.001):
    close = pd.Series(closes, dtype=float)
    return pd.DataFrame({
        "time": pd.date_range("2020-01-01", periods=len(close), freq="D", tz="UTC"),
        "open": close.shift(1).fillna(close.iloc[0]),
        "high": close + spread_hl,
        "low": close - spread_hl,
        "close": close,
    })


class TestIndicators(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(3)
        self.df = make_df(100 + np.cumsum(rng.normal(0, 0.5, 400)))

    def test_sma_matches_manual_mean(self):
        s = ind.sma(self.df["close"], 5)
        self.assertAlmostEqual(s.iloc[10], self.df["close"].iloc[6:11].mean())

    def test_indicators_are_causal(self):
        """Truncating the future must not change past indicator values."""
        full = ind.rsi(self.df["close"], 14)
        cut = ind.rsi(self.df["close"].iloc[:200], 14)
        pd.testing.assert_series_equal(full.iloc[:200], cut, check_names=False)

    def test_rsi_bounds_and_warmup(self):
        r = ind.rsi(self.df["close"], 14)
        self.assertTrue(r.dropna().between(0, 100).all())
        self.assertTrue(r.iloc[:13].isna().all())

    def test_rsi_all_gains_is_100(self):
        r = ind.rsi(pd.Series(np.arange(1, 60, dtype=float)), 14)
        self.assertAlmostEqual(r.iloc[-1], 100.0)

    def test_atr_positive(self):
        self.assertTrue((ind.atr(self.df).dropna() > 0).all())

    def test_supertrend_only_pm_one(self):
        self.assertTrue(set(ind.supertrend(self.df).unique()) <= {-1.0, 1.0})


class TestBacktest(unittest.TestCase):
    def test_flat_signal_never_trades(self):
        df = make_df(np.linspace(100, 110, 200))
        r = backtest.run(df, pd.Series(0.0, index=df.index), spread=0.01)
        self.assertEqual(r.n_trades, 0)
        self.assertEqual(r.metrics["final_equity"], 1000.0)

    def test_no_lookahead_signal_executes_next_bar(self):
        """A signal on the last bar cannot produce a trade -- there is no next bar."""
        df = make_df(np.linspace(100, 110, 100))
        sig = pd.Series(0.0, index=df.index)
        sig.iloc[-1] = 1.0
        r = backtest.run(df, sig, spread=0.0)
        self.assertEqual(r.n_trades, 0)

    def test_spread_is_charged(self):
        df = make_df(np.linspace(100, 110, 150))
        sig = pd.Series(1.0, index=df.index)
        free = backtest.run(df, sig, spread=0.0)
        costly = backtest.run(df, sig, spread=0.5)
        self.assertLess(costly.metrics["final_equity"], free.metrics["final_equity"])

    def test_stop_loss_caps_loss_on_gap_down(self):
        # Rally then collapse: the stop must exit, not ride it to the bottom.
        closes = list(np.linspace(100, 120, 60)) + list(np.linspace(120, 60, 40))
        df = make_df(closes)
        sig = pd.Series(1.0, index=df.index)
        r = backtest.run(df, sig, spread=0.0, stop_atr_mult=1.0)
        self.assertTrue(any(t.reason == "stop" for t in r.trades))

    def test_profit_factor_capped_when_no_losses(self):
        df = make_df(np.linspace(100, 200, 120))
        r = backtest.run(df, pd.Series(1.0, index=df.index), spread=0.0, stop_atr_mult=10.0)
        self.assertLessEqual(r.profit_factor, 99.0)

    def test_risk_sizing_scales_position(self):
        df = make_df(np.linspace(100, 130, 200))
        small = backtest.run(df, pd.Series(1.0, index=df.index), spread=0.0, risk_per_trade=0.01)
        big = backtest.run(df, pd.Series(1.0, index=df.index), spread=0.0, risk_per_trade=0.05)
        self.assertGreater(big.trades[0].size, small.trades[0].size)

    def test_mismatched_signal_length_rejected(self):
        df = make_df(np.linspace(100, 110, 50))
        with self.assertRaises(ValueError):
            backtest.run(df, pd.Series([1.0, 0.0]), spread=0.0)


class TestStrategies(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(5)
        self.df = make_df(100 + np.cumsum(rng.normal(0, 0.6, 500)))

    def test_registry_populated(self):
        self.assertGreaterEqual(len(S.REGISTRY), 50)

    def test_all_signals_valid_and_aligned(self):
        for strategy in S.all_strategies():
            with self.subTest(strategy=strategy.name):
                sig = strategy.signal(self.df)
                self.assertEqual(len(sig), len(self.df))
                self.assertTrue(set(np.unique(sig)) <= {-1.0, 0.0, 1.0})
                self.assertFalse(sig.isna().any())

    def test_duplicate_registration_rejected(self):
        with self.assertRaises(ValueError):
            S.register("sma_cross_10_30", "x", S.TREND)(lambda df: df["close"] * 0)

    def test_trend_strategy_follows_a_trend(self):
        up = make_df(np.linspace(100, 200, 300))
        self.assertEqual(S.REGISTRY["sma_cross_10_30"].signal(up).iloc[-1], 1.0)
        down = make_df(np.linspace(200, 100, 300))
        self.assertEqual(S.REGISTRY["sma_cross_10_30"].signal(down).iloc[-1], -1.0)


class TestValidation(unittest.TestCase):
    def test_split_is_chronological(self):
        df = make_df(np.arange(100, 300, dtype=float))
        a, b = V.split(df, 0.6)
        self.assertEqual(len(a), 120)
        self.assertTrue(a["time"].max() < b["time"].min())

    def test_luck_baseline_returns_a_bar(self):
        rng = np.random.default_rng(1)
        df = make_df(100 + np.cumsum(rng.normal(0, 0.5, 400)))
        base = V.luck_baseline(df, spread=0.01, n_random=20)
        self.assertIn("pf_p95", base)
        self.assertGreater(base["pf_p95"], 0)

    def test_screen_flags_insufficient_trades(self):
        rng = np.random.default_rng(2)
        df = make_df(100 + np.cumsum(rng.normal(0, 0.5, 300)))
        verdicts, _ = V.screen(
            [S.REGISTRY["zscore_revert_100_2.5"]], {"X": df}, {"X": 0.01}, n_random=10
        )
        self.assertEqual(len(verdicts), 1)
        self.assertFalse(verdicts[0].passed)


class TestPortfolio(unittest.TestCase):
    def test_equal_weight_splits_capital(self):
        rng = np.random.default_rng(9)
        df = make_df(100 + np.cumsum(rng.normal(0, 0.5, 400)))
        names = ["keltner_revert", "rsi7_revert_25_75", "roc_momentum_20"]
        p = portfolio.run(df, [S.REGISTRY[n] for n in names], spread=0.01, initial_equity=999.0)
        self.assertEqual(len(p["per_strategy"]), 3)
        self.assertAlmostEqual(p["equity"].iloc[0], 999.0, places=6)

    def test_empty_portfolio_rejected(self):
        df = make_df(np.linspace(100, 110, 50))
        with self.assertRaises(ValueError):
            portfolio.run(df, [], spread=0.0)


class TestBotLogic(unittest.TestCase):
    def test_votes_combine_to_net_direction(self):
        df = make_df(np.linspace(100, 200, 300))
        pos, votes = desired_position(df, ("sma_cross_10_30", "roc_momentum_20"))
        self.assertEqual(pos, 1)
        self.assertEqual(len(votes), 2)

    def test_conflicting_votes_cancel_to_flat(self):
        df = make_df(np.linspace(100, 200, 300))

        class Fake:
            def __init__(self, v): self.v = v
            def signal(self, d): return pd.Series(float(self.v), index=d.index)

        S.REGISTRY["_t_long"] = Fake(1)
        S.REGISTRY["_t_short"] = Fake(-1)
        try:
            pos, _ = desired_position(df, ("_t_long", "_t_short"))
            self.assertEqual(pos, 0)
        finally:
            del S.REGISTRY["_t_long"], S.REGISTRY["_t_short"]

    def test_unknown_strategy_rejected(self):
        df = make_df(np.linspace(100, 110, 300))
        with self.assertRaises(Exception):
            desired_position(df, ("does_not_exist",))

    def test_default_config_is_demo_only(self):
        self.assertFalse(BotConfig().allow_live)


if __name__ == "__main__":
    unittest.main()
