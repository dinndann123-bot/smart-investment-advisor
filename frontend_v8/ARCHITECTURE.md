# Smart Investment Advisor — Frontend v8

## Non-negotiable architecture
One frontend application. One canonical scanner contract. One canonical chart contract. No runtime UI patches, injected loaders, hidden stock fallbacks, duplicated Top-10 state, or placeholder market values presented as real data.

## Screens
1. Dashboard — live market regime, S&P 500, Nasdaq, Dow, VIX, leading day-trade candidate, previous-day strategy review, scan/data freshness.
2. Day Trading — canonical predictive Top-10, rank, price, session change, gap, RVOL, volume, stage, score, entry zone, target, stop, timing, data timestamp/source.
3. Long Term — separate strategy/data state; never reuse day-trading rankings.
4. Portfolio — positions/watchlist/performance from a dedicated portfolio contract; empty state until real data exists.
5. Learning — strategy version, observations, prediction outcomes, feature explanations and validation statistics. Never label confidence as historical success rate.

## Stock workspace
Clicking a symbol opens one reusable stock workspace with 1D/1W/1M/3M/1Y/5Y charts from /api/market/chart/{symbol}; strategy features; entry/target/stop when supplied by backend; source/feed/last market timestamp.

## Data rules
- /api/scanner/day is the only owner of Day Trading Top-10.
- /api/market/chart/{symbol} is the only owner of chart bars.
- Missing data renders as unavailable, never stale hard-coded values.
- Premarket labels must state the actual feed/delay.
- Regular-session labels must state the actual feed.
- UI refresh does not mutate strategy logic.

## Design system
Dark institutional terminal aesthetic inspired by the approved reference: deep navy background, restrained gold accent, compact information density, strong hierarchy, responsive cards, real navigation, mobile-first. No toy icons, oversized empty areas, generic admin-dashboard styling, or fake decorative charts.

## Release gate
Do not replace production root until: all five routes/views work; navigation works; day Top-10 renders from API; stock workspace loads a real chart; market index cards are backed by real data or explicitly unavailable; mobile layout is checked; no hard-coded ticker list exists; no runtime patch is required.