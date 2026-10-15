# Changelog

Grouped by milestone. One line per user-visible change (new command, schema change, behaviour change).
Fine-grained history lives in git commits.

## Milestone 1 - Data Crawling

### Added
- Project skeleton: `src/introds` package, CLI (`init-db`, `spans`), `.env` / Colab Secrets loading.
- SQLite schema for crawl state, metadata, references and performance metrics.
- `RunMetrics`: per-stage timing and background RSS / disk sampling.
- Per-host `RateLimiter`.
