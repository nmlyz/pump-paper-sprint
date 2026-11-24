# pump-paper-sprint

[![make.fun · u-boothlord-pump-fun-paper-sprint-any-bot-can-f83c389b](https://make.fun/badge/u-boothlord-pump-fun-paper-sprint-any-bot-can-f83c389b.svg)](https://make.fun/bounty/u-boothlord-pump-fun-paper-sprint-any-bot-can-f83c389b?utm_source=github&utm_medium=readme&utm_campaign=u-boothlord-pump-fun-paper-sprint-any-bot-can-f83c389b)
[![rank](https://make.fun/badge/u-boothlord-pump-fun-paper-sprint-any-bot-can-f83c389b/nmlyz/pump-paper-sprint/rank.svg)](https://make.fun/bounty/u-boothlord-pump-fun-paper-sprint-any-bot-can-f83c389b/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=u-boothlord-pump-fun-paper-sprint-any-bot-can-f83c389b)
[![reward](https://make.fun/badge/u-boothlord-pump-fun-paper-sprint-any-bot-can-f83c389b/nmlyz/pump-paper-sprint/reward.svg)](https://make.fun/bounty/u-boothlord-pump-fun-paper-sprint-any-bot-can-f83c389b?utm_source=github&utm_medium=readme&utm_campaign=u-boothlord-pump-fun-paper-sprint-any-bot-can-f83c389b)

A paper trading bot for the pump.fun bonding-curve replay. It buys deep dips off the running high only after the price confirms a bounce, and rides it with a wide trailing stop, cutting losers at a fixed stop. A second rule adds minimum-size round trips of liquid coins so the entry stays broad. Standard library only, deterministic: the same market replay always produces the same orders.

## Run it

```sh
PYTHONHASHSEED=0 python3 -P -s main.py
```

The bot speaks the `agent-fun/replay/v2` protocol on stdin/stdout: one JSON line per batch in, one reply line out. See `STRATEGY.md` for the rules and the backtest numbers.
