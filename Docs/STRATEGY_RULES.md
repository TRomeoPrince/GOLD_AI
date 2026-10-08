# GOLD_AI strategy rulebook

Every strategy is an independent entry model. Cross-strategy agreement is recorded as research data, never required by default.

## MARKET_STRUCTURE — ACTIVE
M5 HH/HL and LL/LH structure with pullback/continuation confirmation.

## SUPPORT_RESISTANCE — ACTIVE
Source basis: the supplied price-action material shows repeated horizontal support/resistance, price reactions at those levels, and resistance/support role reversal. The bot clusters repeated M5 swing points into levels and trades a directional rejection from a repeatedly tested level.

Engineering parameters: pivot span, ATR clustering/touch tolerance, stop buffer and 1.5R research target.

## RANGE_BREAK — ACTIVE
Source basis: supplied price-action material explicitly illustrates Breakout -> Retest and support becoming resistance / resistance becoming support. The model first defines a compact M5 range, requires a body-close breakout, then requires the next completed candle to retest and close back on the breakout side.

Engineering parameters: 12-bar range, ATR width/body/touch thresholds, stop buffer and 1.5R target.

## SMART_MONEY_5M — ACTIVE
Source basis: supplied **5-Minute Smart Money Scalping Strategy (Full Breakdown)** material shows supply/demand zones, DBR/RBD/RBR/DBD-style departure structures, break of market structure, candle strength, freshness and first return/reaction at a zone.

The research implementation detects a strong M5 displacement that breaks recent structure, treats the immediately preceding candle as the zone/base, requires that zone to remain fresh, and waits for a first retest with directional confirmation.

Engineering parameters: displacement >= 1 ATR, structural lookback, zone stop buffer and 2R target.

These numeric thresholds are research operationalisations, not claimed verbatim values from the videos. They are deliberately logged so later backtests can tune or reject them.
