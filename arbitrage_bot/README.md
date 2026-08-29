# Solana arbitrage scanner

Finds round-trip price dislocations on Solana — `SOL → token → SOL` — by pricing
both legs through the [Jupiter](https://jup.ag) aggregator, subtracting every
cost it can know up front, and recording what's left.

**It runs in paper mode by default and does not touch your wallet.** Live swap
submission is deliberately left unimplemented; see [Going live](#going-live).

## Read this before you run it

This was built after a viral post claiming a student turned $1 into $400,000
with a Solana arbitrage bot. That claim is unverified social-media content.
Here is what this scanner actually measured against the live Jupiter API while
it was being written:

```
size=0.1 SOL   SOL->JUP->SOL   gross=+0.066%   net=-0.284%
size=1.0 SOL   SOL->JUP->SOL   gross=+0.030%   net=-0.005%
size=5.0 SOL   SOL->JUP->SOL   gross=-0.017%   net=-0.024%
```

Every single cycle across five liquid tokens and three sizes was **net
negative**. That is not a bug in the scanner — it is the market working
correctly. Three forces make it so:

1. **Gross gaps are tiny.** Jupiter already routes across every major DEX, so
   the obvious two-venue gaps are arbitraged away before you see them. What's
   left is 1–7 bps.
2. **Fees are fixed per cycle.** Two signatures plus two priority fees, ~350k
   lamports at the example settings. At 0.1 SOL that's 0.35% — five times any
   gap on offer. Raising size dilutes the fixed fee...
3. **...but price impact grows with size.** At 5 SOL the gross edge had already
   gone negative from impact alone. The window where fees are small *and*
   impact is small is narrow, and professional bots with Jito bundles and
   co-located infrastructure are already sitting in it.

So the realistic expectation is: **you will not find free money with a public
RPC and a public quote API.** What you *can* do is measure honestly — which is
what this tool is for. Run it for a few days, read the ledger, and let the data
decide whether there's anything here worth risking funds on.

## What you need to sign up for

- **Detection / paper trading: nothing.** Jupiter's lite quote API is public —
  no account, no key.
- **Live trading: a Solana keypair**, which you generate yourself. That's
  self-custody, not a platform signup.
- **Optional:** a paid RPC provider (Helius, Triton, QuickNode) if the free
  public RPC rate-limits you. Start without it.

## Install

Nothing to install. The scanner is pure standard library on Python 3.10+.
(Live execution would additionally need `solders` and `solana`.)

## Usage

```bash
cp arbitrage_bot/config.example.json config.json

# one pass over every configured token
python -m arbitrage_bot scan --config config.json -v

# continuous scanning until Ctrl-C
python -m arbitrage_bot run --config config.json

# what the ledger says so far
python -m arbitrage_bot report --config config.json
```

Useful overrides: `--size` (SOL per attempt), `--min-profit-pct`,
`--poll-interval`, `--iterations`, `--ledger`.

## Configuration

See `config.example.json`. The fields that matter most:

| Field | Meaning |
| --- | --- |
| `trade_size_sol` | Notional per attempt. Quotes are priced at exactly this size, because AMM edge is size-dependent. |
| `min_profit_pct` | Minimum **net** edge, as a fraction. `0.003` == 0.3%. |
| `priority_fee_lamports` | Budgeted per transaction; a cycle pays it twice. |
| `tip_lamports` | Jito-style bundle tip, per cycle attempt. |
| `landing_rate` | Fraction of attempts assumed to land. Below 1.0, fees are grossed up — failed sends still burn fees, so winners must carry them. |
| `slippage_bps` | Slippage tolerance sent to the aggregator. |
| `max_live_trade_size_sol` | Hard per-trade ceiling, enforced independently of `trade_size_sol`. |
| `max_session_loss_sol` | Session stops once cumulative PnL falls below this. |
| `dry_run` | `true` (default) = paper. Must be false *and* `--live` passed for real orders. |

Costs are modelled in `Config.cycle_fee_lamports`:

```
(2 * (signature_fee + priority_fee) + tip) / landing_rate
```

## How detection works

`detector.evaluate_cycle` prices `SOL → token` at the configured notional, then
prices `token → SOL` **using exactly what the first leg returned** — not a round
number. Quoting a different amount on the return leg prices a trade you cannot
actually execute, and is the most common way a backtest invents profit that
isn't there.

DEX and AMM fees are already baked into the aggregator's output amounts, so the
detector adds only what the chain charges on top.

Every evaluation is written to the ledger, losers included. The losers are the
point: they tell you whether the strategy is merely *fee-bound* (gross positive,
net negative — worth revisiting at different size or with a cheaper execution
path) or genuinely *absent* (gross negative).

## Paper mode's blind spot

Paper fills book the detector's own estimate, which assumes every attempt lands
at the quoted price with nothing in front of it. Real execution loses to
latency, competing bots, and pool state moving between quote and landing.

**Treat paper PnL as a strict upper bound.** An edge that barely clears the
threshold on paper is a loss in production. The `landing_rate` setting exists to
make that pessimism explicit in the fee model — set it to what you actually
observe, not to 1.0.

## Going live

`LiveExecutor._submit` raises `NotImplementedError` on purpose. Wiring it up
means requesting `/swap` transactions per leg, signing with your keypair,
sending with a priority fee, and measuring the **realized** lamport delta from
the confirmed transaction rather than trusting the quote.

Before you write that code, satisfy all of:

- a paper run over several days shows a positive edge *after* the fee model,
- with a `landing_rate` set from observed landing behaviour, not optimism,
- at a size whose price impact you've measured, not assumed,
- and you're prepared to lose the funds anyway.

Even then, constructing a `LiveExecutor` requires `dry_run: false`, `--live`, a
size under `max_live_trade_size_sol`, and a keypair file at
`$SOLANA_KEYPAIR_PATH`. All four are checked before anything is signed.

## Tests

```bash
python -m unittest discover -s arbitrage_bot/tests -t .
```

63 tests, no network access required — the Jupiter transport is injectable and
the tests drive it with recorded payloads.

## Layout

| File | Role |
| --- | --- |
| `config.py` | Config dataclasses, validation, fee model |
| `jupiter.py` | Quote client (stdlib HTTP, injectable transport) |
| `detector.py` | Cycle evaluation and scanning |
| `executor.py` | Paper executor, live executor, risk guard |
| `ledger.py` | JSONL record + PnL summary |
| `cli.py` | `scan` / `run` / `report` |

## Disclaimer

This is software for measuring a market, not financial advice. Automated trading
can lose money quickly and irreversibly, and on-chain losses cannot be reversed.
You are responsible for any funds you put behind it.
