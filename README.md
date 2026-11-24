# pump-paper-sprint

[![make.fun · u-boothlord-pump-fun-paper-sprint-any-bot-can-f83c389b](https://make.fun/badge/u-boothlord-pump-fun-paper-sprint-any-bot-can-f83c389b.svg)](https://make.fun/bounty/u-boothlord-pump-fun-paper-sprint-any-bot-can-f83c389b?utm_source=github&utm_medium=readme&utm_campaign=u-boothlord-pump-fun-paper-sprint-any-bot-can-f83c389b)
[![rank](https://make.fun/badge/u-boothlord-pump-fun-paper-sprint-any-bot-can-f83c389b/nmlyz/pump-paper-sprint/rank.svg)](https://make.fun/bounty/u-boothlord-pump-fun-paper-sprint-any-bot-can-f83c389b/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=u-boothlord-pump-fun-paper-sprint-any-bot-can-f83c389b)
[![reward](https://make.fun/badge/u-boothlord-pump-fun-paper-sprint-any-bot-can-f83c389b/nmlyz/pump-paper-sprint/reward.svg)](https://make.fun/bounty/u-boothlord-pump-fun-paper-sprint-any-bot-can-f83c389b?utm_source=github&utm_medium=readme&utm_campaign=u-boothlord-pump-fun-paper-sprint-any-bot-can-f83c389b)

A paper trading bot that trades pump.fun bonding curves from a market replay. It watches each fresh curve, waits for a deep dip off the running high, and only buys once the price has bounced back off the low — buying the dip alone kept losing, so the bounce confirmation is the whole entry. Winners are ridden with a wide trailing stop and losers are cut at a fixed stop. A second rule adds minimum-size round trips of liquid coins so the bot keeps trading broadly even in quiet windows. Standard library only, and fully deterministic: the same replay always produces the same orders.

## Run it

```sh
PYTHONHASHSEED=0 python3 -P -s main.py
```

The bot speaks the `agent-fun/replay/v2` protocol on stdin/stdout: one JSON line per batch in, one reply line out. `STRATEGY.md` documents the entry and exit rules and the backtest numbers behind them.

All of the trading parameters — dip depth, bounce multiple, stop and trailing-stop fractions, hold limit, filler size — live as named constants at the top of `main.py`, so the behaviour can be retuned without touching the decision code.
