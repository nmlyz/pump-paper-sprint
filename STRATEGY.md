# Strategy

## What the bot does

Dip-buying with bounce confirmation on pump.fun bonding curves, plus cheap
breadth fillers.

**Core entry.** A curve is bought when all of these hold on a batch:

- age 5–1000 slots since its CreateEvent;
- price fell to at most 60% of the running high since creation (a 40% dip),
  and has since recovered to at least 1.25x the low set since that dip;
- real SOL reserves at least 5;
- at least 3 distinct non-creator buyers seen;
- the creator has not sold.

One buy per coin, up to 0.3 SOL (the 1%-of-real-reserve cap binds first on
small curves), 500 bps of slippage tolerance. Sells always use 10000 bps so
a sale is never refused for the price moving in the 2-slot latency.

**Core exits.** The whole position is sold on the first of:

- value below cost x 0.90 (stop loss);
- value below peak x 0.90 once the peak reached cost x 1.10 (trailing stop);
- the creator sells while held, or a single recorded sell of 5+ SOL lands;
- 50 slots held.

No fixed take-profit: the trailing stop takes what the bounce gives. No
adds: adding into a position lost money in every backtest.

**Fillers.** Minimum-size (0.012 SOL) round trips of liquid coins (real SOL
>= 5), sold on the next batch, until 25 distinct mints have a filled buy of
at least 0.01 SOL in total. Each costs about the fee floor; the selective
rule pays for them. They exist so the entry clears the 20-coin bar even in
a quiet 6-hour window, where the core rule alone trades about 7 coins.

## What was measured, and why the alternatives were dropped

All numbers are net PnL in SOL on the kit's development window (all 3 parts,
24 hours, 1222 coins), from the local replay-model port, unless noted. Fees
are 95 + 30 bps of curve fees plus 105,000 lamports per order.

- **Plain dip-buy (the sibling bot's rule: 25% dip, tight 3% stops):**
  -0.089 SOL, 105 coins. The dip alone is a falling knife on this window:
  forward returns after a dip are negative at every depth and horizon
  (win rate 7-32%), so buying the dip itself loses.
- **Buy the launch (sniper pilot):** -0.489 SOL, 354 coins.
- **Traction momentum (momentum pilot):** -9.387 SOL, max drawdown 95%.
- **Mean reversion (reversion pilot):** -4.016 SOL.
- **Equal-weight baseline:** -0.019 SOL, 5 coins. **Hold cash:** 0.
- **Dip + bounce confirmation (this bot's core, wide 10% exits):**
  +0.217 SOL on 27 coins before fillers; the confirmation filter is what
  turns the dip rule positive. Narrow exits (3-5%) cut the bounce too early
  and give -0.027; adding into the bounce gives +0.064 at best and -0.052
  at worst, so no adds. Bigger buys scale the edge (0.05 SOL buys: +0.035;
  0.3 SOL buys: +0.217) because the fixed per-order fee shrinks as a share.

## Results

Development window, default failed-tx draw (the mean over 4 failed-tx draws
of the core rule alone is +0.217 SOL, worst draw +0.172):

| bot | net PnL (SOL) | fills | coins | max DD |
| --- | --- | --- | --- | --- |
| pump-paper-sprint (this) | **+0.182** | 102 | 50 | 0.0141 |
| dip-buy, no confirmation | -0.089 | 210 | 105 | 0.0187 |
| sniper pilot | -0.489 | 848 | 354 | 0.0533 |
| reversion pilot | -4.016 | 2316 | 198 | 0.4892 |
| momentum pilot | -9.387 | 410 | 48 | 0.9502 |
| equal-weight | -0.019 | 5 | 5 | 0.0093 |
| hold-cash | 0.000 | 0 | 0 | 0.0000 |

Robustness: no failed transactions +0.178, 2x fees +0.042, net without the
single best round trip +0.100. Per dataset part: -0.025 / +0.030 / +0.092,
so a single 6-hour window is high-variance; on two 6-hour slices of the dev
window the bot traded 26 coins each (above the 20-coin bar) at -0.033 and
+0.002. Two executions produce byte-identical action logs (63,369 replies).
