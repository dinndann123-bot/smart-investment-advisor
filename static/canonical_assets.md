# Canonical production assets

- `canonical_black_gold.css`: presentation-only black/gold design system.
- `data_integrity.js`: read-only cross-view scanner integrity monitor.
- `day_sync_r16.js`: canonical daily Top-10 synchronization; data only.

These modules must not alter strategy scoring. They are staged independently so UI changes cannot silently modify investment-method behavior.
