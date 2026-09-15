# Smart Investment Advisor — Production Architecture

## Source of truth
- FastAPI entry point: `app.py`
- Canonical UI: `static/index.html`
- Day scanner backend: `market_search.py` + API routes in `app.py`
- Long strategy: `long_strategy.py`
- Learning: `explosion_learning.py`
- Historical validation/research: `research_50.py` and validation assets

## Invariants
1. Home day-trading list and Day Trading page consume the same scanner snapshot and ranking.
2. Day scanner returns Top 10 ranked candidates; score is method-fit, never a guaranteed profit probability.
3. Learning/validation code is independent from presentation/theme code.
4. UI assets are linked explicitly from the canonical page; runtime HTML monkey-patching is transitional debt and must be removed only after equivalent behavior is migrated and regression-tested.
5. Black/gold branding is presentation-only and must not alter scanner, scoring, learning, portfolio, or validation logic.
6. `production-stable` remains the rollback point until the clean migration is verified live.

## Legacy debt to retire safely
- root `index.html` duplicate: remove only after confirming no startup/install path references it.
- `sitecustomize.py`: currently injects UI/runtime behavior; migrate feature-by-feature before removal.
- `runtime_fixes.py`: audit imports and move required scanner behavior into normal modules before removal.
- one-off workflows/assets: delete only after proving they are not required by production or validation.

## Release gate
A migration may reach `main` only after: syntax/import checks, scanner API smoke test, Top-10 snapshot consistency check, home/day synchronization check, portfolio smoke test, learning/validation boundary check, and live Render version verification.
