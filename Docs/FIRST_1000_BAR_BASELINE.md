# Baseline Report 001 — first 1,000 M5 bars

This freezes the first successful GOLD_AI multi-strategy historical result before speed optimisation.

Broker: JustMarkets-Live3. Symbol: XAUUSD.c. Bars: 1,000 M5. Total independent observations: 615. Live trading disabled.

**The original engine was R-based only; there was no starting cash balance in this first report.**

| Strategy | Trades | Wins | Losses | Win rate % | Net R | Avg R | Profit factor | Max DD R |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| MOMENTUM_SCALP | 125 | 60 | 65 | 48.000000 | 11.581195 | 0.092650 | 1.182615 | 9.168805 |
| PULLBACK | 70 | 32 | 38 | 45.714286 | 10.000000 | 0.142857 | 1.263158 | 5.500000 |
| RANGE_BREAK | 16 | 10 | 6 | 62.500000 | 9.000000 | 0.562500 | 2.500000 | 4.000000 |
| MARKET_STRUCTURE | 33 | 15 | 18 | 45.454545 | 4.500000 | 0.136364 | 1.250000 | 6.000000 |
| SUPPORT_RESISTANCE | 71 | 30 | 41 | 42.253521 | 4.083821 | 0.056338 | 1.097561 | 10.500000 |
| SMART_MONEY_5M | 7 | 3 | 4 | 42.857143 | 2.000000 | 0.285714 | 1.500000 | 3.000000 |
| POWER_OF_THREE | 108 | 34 | 74 | 31.481481 | -7.353671 | -0.068090 | 0.900626 | 32.000000 |
| LIQUIDITY_SWEEP | 63 | 17 | 46 | 26.984127 | -12.000000 | -0.190476 | 0.739130 | 26.000000 |
| PRICE_ACTION | 122 | 39 | 83 | 31.967213 | -25.019085 | -0.205074 | 0.697558 | 25.223608 |

## R
1R is the amount planned to be lost if a trade reaches its stop. -1R loses one unit of risk; +1.5R earns 1.5 times the risk. Net R is the sum of all trade R-multiples and deliberately assumes no account size.

Example: at a 10,000 USD balance and 0.9% risk, initial 1R = 90 USD, so +1.5R is approximately +135 USD before costs. With percentage compounding, the cash value of 1R changes with balance.

Cash-equity values were not recorded in Baseline 001 and must not be presented as observed historical values. The upgraded engine now accepts explicit starting balance and risk inputs.
