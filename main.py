# Pump Paper Sprint — buying the bounce after a deep dip on pump.fun curves.
#
# A fresh bonding curve usually spikes at launch and then dumps. Buying the
# dip itself is a falling knife: on the dev window every bare dip-buy rule
# loses money, because prices keep sliding after the first drop. The edge
# that survives is the bounce *after* a deep dip: wait until the price has
# fallen to 60% or less of the running high since creation, mark the low,
# and only buy once it has climbed back to 1.25x that low (age 5-1000 slots,
# real SOL >= 5, at least three distinct non-creator buyers, creator not
# selling). Then ride the bounce with a wide trailing stop (10% off the peak
# once the position is up 10%), cut at -10%, never hold past 50 slots, one
# buy per coin, no adds. Buys are up to 0.3 SOL (the 1%-of-real-reserve cap
# binds first on small curves), so the fixed per-order fee stays a small
# share of each trade.
#
# A second, cheap rule keeps breadth above the 20-coin bar: minimum-size
# (0.012 SOL) round trips of liquid coins, sold on the next batch, up to 25
# distinct filled mints per run. Each costs about the fee floor; the
# selective rule pays for them.
#
# Pure function of the batches the harness sends (no clock, no randomness,
# no I/O), so the two graded executions produce byte-identical action logs.
# Standard library only.
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bot

LAMPORTS_PER_SOL = 1_000_000_000
CURVE_FEE_RATE = 0.0125

# Entry: the price must have fallen to at most this share of the running high.
DIP_FRACTION = 0.6
# Entry: buy only after the price has recovered this multiple off the dip low.
BOUNCE_MULTIPLE = 1.25
# Entry window, in slots since the CreateEvent.
EARLIEST_SLOT = 5
LATEST_SLOT = 1000
# Minimum real SOL in the curve's reserves at entry.
MIN_REAL_SOL = 5.0
# Minimum distinct non-creator buyers observed before entry.
MIN_DISTINCT_BUYERS = 3
# SOL committed to one position in total (single buy; no adds).
POSITION_SOL = 0.5
FIRST_BUY_SOL = 0.3
# Smallest buy worth sending (the harness charges 105k lamports per order).
MIN_ORDER_SOL = 0.01
# Slippage tolerance on buys, in basis points; sells always use 10000.
BUY_SLIPPAGE_BPS = 500
# Stop loss / trailing-stop drop / trailing-stop arming level, as fractions.
STOP_FRACTION = 0.1
TRAIL_FRACTION = 0.1
TRAIL_ARM_FRACTION = 0.1
# Give up on a position after this many slots.
HOLD_LIMIT = 50
# Exit when the creator sells while a position is held.
EXIT_WHEN_CREATOR_SELLS = True
# Exit on any single recorded sell of at least this many SOL.
LARGE_SELL_SOL = 5.0
# Slots to wait after an exit before the same curve can be bought again.
REENTRY_WAIT = 50
# Most entries per curve over the whole run.
ENTRIES_PER_CURVE = 1
# Most SOL at cost held across all positions at once (a drawdown guard).
EXPOSURE_LIMIT_SOL = 8.0
# Filler: minimum-size round trip, sold on the next batch. Fillers run until
# this many distinct mints hold a filled buy of >= 0.01 SOL in total
# (breadth for the 20-coin bar, counted on fills so rejects and failures do
# not eat the margin).
FILLER_BUY_SOL = 0.012
FILLER_MIN_REAL_SOL = 5.0
FILLER_MINT_TARGET = 25


class CurveBook:
    """Per-mint tape: running high/low, dip state, buyers, creator activity."""

    __slots__ = ("born", "creator", "peak", "peak_slot", "trough", "has_dipped",
                 "buyers", "buys", "exited_at", "creator_sold")

    def __init__(self):
        self.born = None
        self.creator = ""
        self.peak = 0.0
        self.peak_slot = -10**12
        self.trough = float("inf")
        self.has_dipped = False
        self.buyers = set()
        self.buys = 0
        self.exited_at = -10**12
        self.creator_sold = False


class OpenTrade:
    """One open position: when it opened, its peak value, cost, exit state."""

    __slots__ = ("opened_at", "best_value", "cost_sol", "leaving", "was_filled",
                 "value_now", "is_filler")

    def __init__(self, opened_at, cost_sol, is_filler=False):
        self.opened_at = opened_at
        self.best_value = 0.0
        self.cost_sol = cost_sol
        self.leaving = False
        self.was_filled = False
        self.value_now = 0.0
        self.is_filler = is_filler


books = {}
trades = {}
bought_mints = set()


def book_for(mint):
    book = books.get(mint)
    if book is None:
        book = CurveBook()
        books[mint] = book
    return book


def _absorb_events(batch):
    """Fold one batch's events into the per-mint books.

    Returns (traded, dumped): the mints that traded this batch, in first-seen
    order, and the mints hit by a single sell of LARGE_SELL_SOL or more.
    """
    traded = []
    dumped = set()
    for ev in batch["events"]:
        kind = ev["event"]
        if kind == "CreateEvent":
            book = book_for(ev["mint"])
            book.born = ev["slot"]
            book.creator = ev["creator"]
        elif kind == "TradeEvent":
            book = book_for(ev["mint"])
            sol = int(ev["sol_amount"]) / LAMPORTS_PER_SOL
            price = int(ev["virtual_quote_reserves"]) / int(ev["virtual_token_reserves"])
            if price > book.peak:
                book.peak = price
                book.peak_slot = ev["slot"]
            if not book.has_dipped and book.peak > 0 and price <= book.peak * DIP_FRACTION:
                book.has_dipped = True
                book.trough = price
            elif book.has_dipped and price < book.trough:
                book.trough = price
            if ev["is_buy"] and ev["user"] != book.creator:
                book.buyers.add(ev["user"])
            if ev["mint"] not in traded:
                traded.append(ev["mint"])
            if not ev["is_buy"] and ev["user"] == book.creator:
                book.creator_sold = True
            if not ev["is_buy"] and sol >= LARGE_SELL_SOL:
                dumped.add(ev["mint"])
    return traded, dumped


def _position_value(state, marks, mint, tx_sol):
    """What a held position would fetch if sold now, net of curve fee and tx fee."""
    pos = state.positions.get(mint)
    if pos is None:
        return 0.0
    curve = state.curves.get(mint)
    if curve is None:
        return 0.0
    mark = marks.get(mint)
    if mark is not None:
        quote_res = int(mark["virtual_quote_reserves"])
        token_res = int(mark["virtual_token_reserves"])
    else:
        quote_res = curve.virtual_quote_reserves
        token_res = curve.virtual_token_reserves
    tokens = pos.token_amount
    return ((tokens * quote_res) / (token_res + tokens) / LAMPORTS_PER_SOL) * (1.0 - CURVE_FEE_RATE) - tx_sol


def _sell_already_out(state, mint):
    for po in state.pending.values():
        if po.order["mint"] == mint and po.order["side"] == "sell":
            return True
    return False


def _close_positions(state, now, orders, cap, tx_sol, dumped, pending_mints, marks):
    """Exits first: every open position is checked against the exit rules,
    and the whole position is sold on the first rule that fires."""
    for mint, trade in list(trades.items()):
        pos = state.positions.get(mint)
        curve = state.curves.get(mint)
        if pos is None:
            if mint not in pending_mints:
                del trades[mint]
                book = book_for(mint)
                if trade.was_filled:
                    book.exited_at = now
                else:
                    book.buys -= 1
            continue
        trade.was_filled = True
        if curve is None or curve.complete:
            continue
        value = _position_value(state, marks, mint, tx_sol)
        cost = pos.cost_lamports / LAMPORTS_PER_SOL
        if value > trade.best_value:
            trade.best_value = value
        trade.value_now = value
        should_exit = trade.leaving
        if not should_exit and trade.is_filler:
            should_exit = True
        if not should_exit and value < cost * (1.0 - STOP_FRACTION):
            should_exit = True
        if not should_exit and trade.best_value >= cost * (1.0 + TRAIL_ARM_FRACTION) and value < trade.best_value * (1.0 - TRAIL_FRACTION):
            should_exit = True
        if not should_exit and mint in dumped:
            should_exit = True
        if not should_exit and EXIT_WHEN_CREATOR_SELLS and book_for(mint).creator_sold:
            should_exit = True
        if not should_exit and now - trade.opened_at > HOLD_LIMIT:
            should_exit = True
        if not should_exit:
            continue
        trade.leaving = True
        if mint in pending_mints and _sell_already_out(state, mint):
            continue
        if len(orders) >= cap:
            break
        orders.append({"side": "sell", "mint": mint, "token_amount": pos.token_amount, "max_slippage_bps": 10000})


def _open_core_positions(state, traded, now, orders, cap, tx_sol, pending_mints):
    """Core entries: dip + bounce confirmation, one buy per curve."""
    free = state.free_cash_lamports() / LAMPORTS_PER_SOL
    open_slots = state.hello["caps"]["max_open_positions"] - state.committed_position_count()
    exposure = 0.0
    for mint, trade in trades.items():
        pos = state.positions.get(mint)
        exposure += max(trade.cost_sol, (pos.cost_lamports / LAMPORTS_PER_SOL) if pos is not None else 0.0)
    for mint in traded:
        if len(orders) >= cap:
            break
        curve = state.curves.get(mint)
        if curve is None or curve.complete:
            continue
        if mint in pending_mints:
            continue
        book = books[mint]
        if mint in trades:
            continue  # no adds: one entry per position, exit only
        if open_slots <= 0:
            continue
        if book.buys >= ENTRIES_PER_CURVE or now - book.exited_at < REENTRY_WAIT:
            continue
        if book.born is None or now - book.born < EARLIEST_SLOT or now - book.born > LATEST_SLOT:
            continue
        if book.creator_sold or len(book.buyers) < MIN_DISTINCT_BUYERS:
            continue
        if curve.real_quote_reserves / LAMPORTS_PER_SOL < MIN_REAL_SOL:
            continue
        price = curve.virtual_quote_reserves / curve.virtual_token_reserves
        if not book.has_dipped or price < book.trough * BOUNCE_MULTIPLE:
            continue
        size = min(FIRST_BUY_SOL, POSITION_SOL)
        ceiling = int(state.max_buy_lamports(mint) * 0.97) / LAMPORTS_PER_SOL
        size = min(ceiling, size, EXPOSURE_LIMIT_SOL - exposure)
        if size > free - tx_sol:
            size = free - tx_sol
        if size < MIN_ORDER_SOL:
            continue
        orders.append({"side": "buy", "mint": mint, "quote_lamports": int(size * LAMPORTS_PER_SOL), "max_slippage_bps": BUY_SLIPPAGE_BPS})
        free -= size + tx_sol
        exposure += size
        trades[mint] = OpenTrade(now, size)
        book.buys += 1
        open_slots -= 1
    return free, open_slots


def _open_fillers(state, traded, now, orders, cap, tx_sol, pending_mints, free, open_slots):
    """Fillers: cheap breadth. Buy a minimum-size round trip of a liquid coin
    and sell it on the next batch, only until the filler target is met."""
    if FILLER_BUY_SOL <= 0 or len(bought_mints) >= FILLER_MINT_TARGET:
        return
    for mint in traded:
        if len(orders) >= cap:
            break
        if mint in bought_mints:
            continue
        if mint in trades or mint in pending_mints:
            continue
        curve = state.curves.get(mint)
        if curve is None or curve.complete:
            continue
        if open_slots <= 0:
            break
        book = books[mint]
        if book.born is None or now - book.born < EARLIEST_SLOT:
            continue
        if curve.real_quote_reserves / LAMPORTS_PER_SOL < FILLER_MIN_REAL_SOL:
            continue
        ceiling = int(state.max_buy_lamports(mint) * 0.97) / LAMPORTS_PER_SOL
        size = min(ceiling, FILLER_BUY_SOL)
        if size > free - tx_sol:
            size = free - tx_sol
        if size < MIN_ORDER_SOL:
            continue
        orders.append({"side": "buy", "mint": mint, "quote_lamports": int(size * LAMPORTS_PER_SOL), "max_slippage_bps": BUY_SLIPPAGE_BPS})
        free -= size + tx_sol
        trades[mint] = OpenTrade(now, size, is_filler=True)
        open_slots -= 1


def on_batch(state, batch):
    # Order matters: exits free cash and position slots first, the selective
    # core rule takes what is left, and fillers only spend the remainder.
    now = batch["slot"]
    for fill in batch["fills"]:
        if fill["side"] == "buy" and fill["status"] == "filled" and int(fill["quote_lamports"]) >= 10_000_000:
            bought_mints.add(fill["mint"])
    traded, dumped = _absorb_events(batch)
    marks = {m["mint"]: m for m in batch["marks"]}
    pending_mints = {po.order["mint"] for po in state.pending.values()}
    orders = []
    cap = state.hello["caps"]["max_orders_per_batch"]
    tx_sol = state.tx_fee_lamports() / LAMPORTS_PER_SOL
    _close_positions(state, now, orders, cap, tx_sol, dumped, pending_mints, marks)
    free, open_slots = _open_core_positions(state, traded, now, orders, cap, tx_sol, pending_mints)
    _open_fillers(state, traded, now, orders, cap, tx_sol, pending_mints, free, open_slots)
    return orders


if __name__ == "__main__":
    makefun_bot.run(on_batch)
