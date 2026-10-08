# GOLD_AI strategy rulebook

The models in this project are independent. No model needs another model to agree before it can produce a setup.

## MARKET_STRUCTURE — active

Source: uploaded **Market Structure Simplified: A Complete Guide**.

Source-supported concepts visible in the material:
- Uptrend structure is described with Higher Highs (HH) and Higher Lows (HL).
- The inverse structure is used for bearish market structure.
- Pullbacks/reactions around structural swing areas are used to frame continuation opportunities.
- Range-bound conditions are distinguished from trending structure.

Bot operationalisation for research:
- M5 minimum timeframe.
- Confirmed pivots use two candles on each side.
- Bullish regime requires the latest two swing highs and lows to form HH + HL.
- Bearish regime requires LL + LH.
- Entry candidate occurs only on a pullback to the latest structural swing area followed by a directional candle confirmation.
- Structural swing plus an ATR buffer defines invalidation.
- Initial research target is 1.5R.

The pivot span, ATR tolerance/buffer and 1.5R target are measurable engineering parameters. They are not represented as verbatim rules from the source and should be optimized only after collecting data.

## SUPPORT_RESISTANCE — pending source-rule extraction

Independent model; disabled until its source rules are verified.

## RANGE_BREAK — pending source-rule extraction

Independent model; disabled until its source rules are verified.
