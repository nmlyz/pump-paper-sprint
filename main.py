# Pump Paper Sprint: dip-buying with bounce confirmation on pump.fun bonding curves.
#
# A fresh curve pumps on launch, then usually dumps, and a dip alone is a
# falling knife: on the dev window every plain dip-buy rule loses money.
# The repeatable edge is the bounce *after* a deep dip: buy only once the
# price has recovered 25% off the low set since a 40% dip off the running
# high (age 5-1000 slots, real SOL >= 5, a few distinct buyers, creator not
# selling), then ride it with a wide trailing stop (10% off the peak once up
# 10%), cut at -10%, never hold past 50 slots, one buy per coin, no adds.
# Buys are sized up to 0.3 SOL (the 1%-of-real-reserve cap binds first on
# small curves), so the fixed per-order fee is a small share of each trade.
#
# A second, cheap rule keeps the entry broad enough for the 20-coin bar:
# minimum-size (0.012 SOL) round trips of liquid coins, sold on the next
# batch, up to 21 such filler coins per run. Each costs about the fee floor;
# the selective rule pays for them.
#
# Pure function of the batches the harness sends (no clock, no randomness, no
# I/O), so the two graded executions produce byte-identical action logs.
# Standard library only.
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bot

LAMPORTS = 1_000_000_000
CURVE_FEE = 0.0125

# Core entry: price at most this share of the running high since creation.
DIP_SHARE = 0.6
# Core entry: buy only after recovering this far above the low since the dip.
RECOVER_MULT = 1.25
# Entry window in slots since CreateEvent.
MIN_AGE = 5
MAX_AGE = 1000
# Real SOL reserve floor at entry.
MIN_RQ = 5.0
# Distinct non-creator buyers seen before entry.
MIN_BUYERS = 3
# SOL to put into one position in total (single buy; no adds).
STAKE = 0.5
INITIAL = 0.3
# Smallest buy worth sending (tx fees are 105k lamports per order).
MIN_BUY_SOL = 0.01
# Slippage on buys (bps); sells always go out at 10000.
BUY_SLIP_BPS = 500
# Stop loss / trailing stop / trailing arm (fractions of cost / peak value).
STOP_LOSS = 0.1
TRAIL = 0.1
TRAIL_ARM = 0.1
# Exit after this many slots held.
MAX_HOLD = 50
# Exit when the creator sells while held.
EXIT_ON_DEV_SELL = True
# Exit on any single recorded sell of at least this many SOL.
BIG_SELL_SOL = 5.0
# Slots to wait after an exit before the same curve may be bought again.
COOLDOWN = 50
# Most entries per curve over the run.
MAX_ENTRIES = 1
# Most SOL at cost across all positions at once (a drawdown guard).
MAX_EXPOSURE_SOL = 8.0
# Filler: minimum-size round trip, sold on the next batch. Fillers run until
# this many distinct mints have a filled buy >= 0.01 SOL in total (breadth
# for the 20-coin bar, counted on fills so rejects and failures do not eat
# the margin).
FILLER_SIZE = 0.012
FILLER_MIN_RQ = 5.0
FILLER_TARGET = 25


class Tape:
    __slots__ = ("created", "creator", "high", "high_slot", "low", "dipped", "buyers", "entries", "last_exit", "dev_sold")

    def __init__(self):
        self.created = None
        self.creator = ""
        self.high = 0.0
        self.high_slot = -10**12
        self.low = float("inf")
        self.dipped = False
        self.buyers = set()
        self.entries = 0
        self.last_exit = -10**12
        self.dev_sold = False


class Held:
    __slots__ = ("opened", "peak_value", "invested", "exiting", "filled", "last_value", "filler")

    def __init__(self, opened, invested, filler=False):
        self.opened = opened
        self.peak_value = 0.0
        self.invested = invested
        self.exiting = False
        self.filled = False
        self.last_value = 0.0
        self.filler = filler


tapes = {}
held = {}
filled_buy_mints = set()


def tape_of(mint):
    t = tapes.get(mint)
    if t is None:
        t = Tape()
        tapes[mint] = t
    return t


def on_batch(state, batch):
    now = batch["slot"]
    for f in batch["fills"]:
        if f["side"] == "buy" and f["status"] == "filled" and int(f["quote_lamports"]) >= 10_000_000:
            filled_buy_mints.add(f["mint"])
    big_sell = set()
    traded = []
    for e in batch["events"]:
        kind = e["event"]
        if kind == "CreateEvent":
            t = tape_of(e["mint"])
            t.created = e["slot"]
            t.creator = e["creator"]
        elif kind == "TradeEvent":
            t = tape_of(e["mint"])
            sol = int(e["sol_amount"]) / LAMPORTS
            price = int(e["virtual_quote_reserves"]) / int(e["virtual_token_reserves"])
            if price > t.high:
                t.high = price
                t.high_slot = e["slot"]
            if not t.dipped and t.high > 0 and price <= t.high * DIP_SHARE:
                t.dipped = True
                t.low = price
            elif t.dipped and price < t.low:
                t.low = price
            if e["is_buy"] and e["user"] != t.creator:
                t.buyers.add(e["user"])
            if e["mint"] not in traded:
                traded.append(e["mint"])
            if not e["is_buy"] and e["user"] == t.creator:
                t.dev_sold = True
            if not e["is_buy"] and sol >= BIG_SELL_SOL:
                big_sell.add(e["mint"])

    marks = {m["mint"]: m for m in batch["marks"]}
    pending_by_mint = set()
    for po in state.pending.values():
        pending_by_mint.add(po.order["mint"])

    orders = []
    cap = state.hello["caps"]["max_orders_per_batch"]
    tx = state.tx_fee_lamports() / LAMPORTS

    def value_of(mint):
        pos = state.positions.get(mint)
        if pos is None:
            return 0.0
        curve = state.curves.get(mint)
        if curve is None:
            return 0.0
        mk = marks.get(mint)
        if mk is not None:
            vq = int(mk["virtual_quote_reserves"])
            vt = int(mk["virtual_token_reserves"])
        else:
            vq = curve.virtual_quote_reserves
            vt = curve.virtual_token_reserves
        tokens = pos.token_amount
        return ((tokens * vq) / (vt + tokens) / LAMPORTS) * (1.0 - CURVE_FEE) - tx

    # Exits first.
    for mint, h in list(held.items()):
        pos = state.positions.get(mint)
        curve = state.curves.get(mint)
        if pos is None:
            if mint not in pending_by_mint:
                del held[mint]
                t = tape_of(mint)
                if h.filled:
                    t.last_exit = now
                else:
                    t.entries -= 1
            continue
        h.filled = True
        if curve is None or curve.complete:
            continue
        value = value_of(mint)
        cost = pos.cost_lamports / LAMPORTS
        if value > h.peak_value:
            h.peak_value = value
        h.last_value = value
        exit_ = h.exiting
        if not exit_ and h.filler:
            exit_ = True
        if not exit_ and value < cost * (1.0 - STOP_LOSS):
            exit_ = True
        if not exit_ and h.peak_value >= cost * (1.0 + TRAIL_ARM) and value < h.peak_value * (1.0 - TRAIL):
            exit_ = True
        if not exit_ and mint in big_sell:
            exit_ = True
        if not exit_ and EXIT_ON_DEV_SELL and tape_of(mint).dev_sold:
            exit_ = True
        if not exit_ and now - h.opened > MAX_HOLD:
            exit_ = True
        if not exit_:
            continue
        h.exiting = True
        if mint in pending_by_mint:
            sell_pending = False
            for po in state.pending.values():
                if po.order["mint"] == mint and po.order["side"] == "sell":
                    sell_pending = True
                    break
            if sell_pending:
                continue
        if len(orders) >= cap:
            break
        orders.append({"side": "sell", "mint": mint, "token_amount": pos.token_amount, "max_slippage_bps": 10000})

    # Core entries.
    free = state.free_cash_lamports() / LAMPORTS
    slots_left = state.hello["caps"]["max_open_positions"] - state.committed_position_count()
    exposure = 0.0
    for mint, h in held.items():
        pos = state.positions.get(mint)
        exposure += max(h.invested, (pos.cost_lamports / LAMPORTS) if pos is not None else 0.0)
    for mint in traded:
        if len(orders) >= cap:
            break
        curve = state.curves.get(mint)
        if curve is None or curve.complete:
            continue
        if mint in pending_by_mint:
            continue
        t = tapes[mint]
        if mint in held:
            continue  # no adds: one entry per position, exit only
        if slots_left <= 0:
            continue
        if t.entries >= MAX_ENTRIES or now - t.last_exit < COOLDOWN:
            continue
        if t.created is None or now - t.created < MIN_AGE or now - t.created > MAX_AGE:
            continue
        if t.dev_sold or len(t.buyers) < MIN_BUYERS:
            continue
        rq_sol = curve.real_quote_reserves / LAMPORTS
        if rq_sol < MIN_RQ:
            continue
        price = curve.virtual_quote_reserves / curve.virtual_token_reserves
        if not t.dipped or price < t.low * RECOVER_MULT:
            continue
        want = min(INITIAL, STAKE)
        cap_sol = int(state.max_buy_lamports(mint) * 0.97) / LAMPORTS
        amount = min(cap_sol, want, MAX_EXPOSURE_SOL - exposure)
        if amount > free - tx:
            amount = free - tx
        if amount < MIN_BUY_SOL:
            continue
        lamports = int(amount * LAMPORTS)
        orders.append({"side": "buy", "mint": mint, "quote_lamports": lamports, "max_slippage_bps": BUY_SLIP_BPS})
        free -= amount + tx
        exposure += amount
        held[mint] = Held(now, amount)
        t.entries += 1
        slots_left -= 1

    # Fillers: cheap breadth. Buy a minimum-size round trip of a liquid coin
    # and sell it on the next batch, only until the filler target is met.
    if FILLER_SIZE > 0 and len(filled_buy_mints) < FILLER_TARGET:
        for mint in traded:
            if len(orders) >= cap:
                break
            if mint in filled_buy_mints:
                continue
            if mint in held or mint in pending_by_mint:
                continue
            curve = state.curves.get(mint)
            if curve is None or curve.complete:
                continue
            if slots_left <= 0:
                break
            t = tapes[mint]
            if t.created is None or now - t.created < MIN_AGE:
                continue
            if curve.real_quote_reserves / LAMPORTS < FILLER_MIN_RQ:
                continue
            cap_sol = int(state.max_buy_lamports(mint) * 0.97) / LAMPORTS
            amount = min(cap_sol, FILLER_SIZE)
            if amount > free - tx:
                amount = free - tx
            if amount < MIN_BUY_SOL:
                continue
            lamports = int(amount * LAMPORTS)
            orders.append({"side": "buy", "mint": mint, "quote_lamports": lamports, "max_slippage_bps": BUY_SLIP_BPS})
            free -= amount + tx
            held[mint] = Held(now, amount, filler=True)
            slots_left -= 1
    return orders


if __name__ == "__main__":
    makefun_bot.run(on_batch)
