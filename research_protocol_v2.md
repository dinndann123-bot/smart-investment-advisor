# Smart Investment Advisor — Research Protocol v2

## Objective
Replace heuristic tuning with chronological, reproducible evidence. Research is split into two independent models: DAY and SWING/LONG. Production scoring must not change until the relevant model passes holdout validation.

## Cohorts
### Stage A — 10 years
- 500 historical explosion events.
- 250 DAY events: large same-session continuation after an observation cutoff.
- 250 SWING/LONG events: large forward move over 20–252 trading days.
- Matched controls for every event from the same date/market regime and comparable liquidity/price universe.

### Stage B — 15 years
- Expand to 1,000 additional historical events using the same definitions and controls.
- Earlier history with incomplete media data is retained; media fields are `unknown`, never silently scored as zero.

## Anti-bias rules
1. Features must use only information available at the prediction timestamp.
2. Chronological train/validation/holdout splits; no random leakage across time.
3. Survivorship bias: use point-in-time tradable universe when data source permits and explicitly flag limitations otherwise.
4. Corporate actions adjusted consistently.
5. Winners alone are never sufficient: matched non-exploders are mandatory.
6. Thresholds/weights are learned on train only. Holdout is read-only until final evaluation.
7. Keep DAY and SWING/LONG models separate.

## DAY features
- gap from previous close
- move before cutoff
- relative/unexpected volume
- volume acceleration
- early range / volatility
- location within early range / price strength
- liquidity and estimated dollar volume
- market/sector regime
- catalyst category and timestamp when available
- media/attention intensity and freshness when available
- earnings/event flag when available

## SWING/LONG features
- 1m/3m/6m/12m relative momentum
- distance to 52-week high / breakout state
- volume/turnover trend
- volatility regime
- market/sector relative strength
- earnings surprise / earnings momentum when available
- revenue/EPS growth and revisions when available
- catalyst/media attention when available
- liquidity/market-cap controls

## Media handling
Media is a separate evidence family, not a proxy for price momentum. Store source timestamp, publication timestamp, catalyst category, freshness, and availability. Missing archival coverage is `unknown`. Never use post-event coverage to score a pre-event signal.

## Metrics
- precision / recall at production Top-10 threshold
- hit rate for predeclared move thresholds
- false-positive rate
- MFE / MAE
- return after estimated spread/slippage where available
- drawdown
- calibration by score bucket
- stability by year and market regime

## Promotion gate
A candidate Strategy v2 can replace production weights only when:
- holdout precision improves versus current strategy and naive momentum baseline;
- false positives do not materially worsen;
- performance is not concentrated in one year/regime;
- DAY and SWING/LONG each pass independently;
- missing media cannot increase a score;
- all production score components expose provenance and timestamp.

## Current implementation warning
`explosion_learning.py` is a useful prototype but is NOT evidence for the 500/1000 study. It currently uses a fixed recent universe, 15-minute bars, a 10:00 cutoff and six price/volume features. It must not be described as a 10/15-year whole-market backtest.

## Research basis
The protocol explicitly tests findings documented in the literature rather than hard-coding them: intermediate-horizon momentum; the interaction of turnover/attention with momentum; earnings momentum; news-driven short-term continuation; market-regime dependence; and possible long-horizon reversal. These are hypotheses to validate on our cohorts, not assumptions that guarantee returns.
