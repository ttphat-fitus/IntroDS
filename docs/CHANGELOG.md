# Changelog

Grouped by milestone. One line per user-visible change (new command, schema change, behaviour change).
Fine-grained history lives in git commits.

## Milestone 2 - Parsing and Standardization

### Added
- `fetch-bbl`: adds `.bbl` bibliographies to crawled versions that have one but no `.bib` (new table `extra_fetch`, tar-shard backups).
- `parse`: root detection, transitive `\input` / `\include` / `\subfile` / `\import`, comment removal, formatting cleanup, math normalization, hierarchy construction, sentence splitting, BibTeX extraction from `.bib` / `\bibitem` / `.bbl` (natbib and biblatex), reference and element deduplication across versions; parallel and resumable (tables `parse_papers`, `parse_versions`).
- `stats --milestone 2` (report data, example tree) and `export --tables m2` (`elements`, `hierarchy`, `bibtex` Parquet shards).
- `tests/test_parse.py`: pytest suite covering the spec rules on small LaTeX snippets.
- revtex / APS `.bbl` entries are read field by field from `\bibinfo{field}{value}`.

### Fixed
- Letter accents (`\t`, `\u`, `\b`, ...) no longer eat the start of `\textbf`, `\url`, `\bibinfo` in BibTeX values; forced line breaks are removed from titles.
- Root detection judges candidates on their gathered text (class in an `\input` preamble, `\begin{document}` in an `\input` file, templates, supplements, `standalone` figures).
- `\begin{document}` inside a macro definition, `\input` paths built from macros, `.TEX` extensions and bare-CR line endings are handled.

### Changed
- `discover` backs off and retries when the arXiv API answers HTTP 429 instead of exiting.
- `merge` skips tables that the other database does not have.

## Milestone 1 - Data Crawling

### Added
- Project skeleton: `src/introds` package, CLI (`init-db`, `spans`), `.env` / Colab Secrets loading.
- SQLite schema for crawl state, metadata, references and performance metrics.
- `RunMetrics`: per-stage timing and background RSS / disk sampling.
- Per-host `RateLimiter`.
- `discover`: batched arXiv API lookup (100 IDs per request) with a second pass on versioned IDs for intermediate version dates.
- `fetch-src`: per-version download from export.arxiv.org with in-memory extraction of `.tex`/`.bib`; `--keep-bbl`; empty records for PDF-only versions; retries for dropped connections.
- `fetch-refs`: Semantic Scholar batch endpoint (100 papers per request), all references kept.
- `crawl`: discovery, then sources and references concurrently; incremental `--backup-dir`; `backup` / `restore` / `merge` commands.
- `stats` (report numbers and figures data) and `export` (Parquet `papers` / `references`, `metadata.json` / `references.json` per paper).
- `src/colab_crawl.ipynb` to run one member's range on Colab; `docs/guideme.md` walks team members through it (Colab web or the VS Code extension).
- Source downloads resume dropped transfers with HTTP `Range` requests (up to 8 continuations) instead of restarting.
- `restore` resets versions marked `ok` whose files are missing from the backup shards to `pending`.
- `fetch-s3` / `crawl --s3`: fill the latest version of each paper from the requester-pays S3 bulk archive (assuming `AWS_ROLE_ARN` when set) before export.arxiv.org; `verify-s3` re-downloads a sample from export.arxiv.org and compares file hashes.
- HTTP status of every attempt is logged in `timings.http_log`; HTTP 404 marks a version `missing` (empty record, never retried).

### Changed
- Schema: `versions` records `bytes_download`, `bytes_unpacked`, `bytes_kept`, `n_files`, `n_bbl`; `papers` stores `journal_ref` and `categories`; revised dates are derived from `versions`.
- Schema: `versions.origin` (`s3` / `export`) and `timings.http_log`; older databases are migrated on connect, and `merge` copies shared columns only.
- `stats` attributes S3 time per filled version and reports versions by origin.
- `stats` uses a run's last resource sample as its end time when the run was killed with its VM (`ended_at` is NULL).
- `src/colab_crawl.ipynb` runs the crawl inside the cell (a detached process let Colab reclaim the runtime as idle), keeps GNU time and log files on Drive, and accepts a missing Semantic Scholar key.
- `config.get_secret` returns an empty environment variable as "no secret" instead of querying Colab Secrets from a subprocess.
- `RunMetrics` buffers timings in memory and flushes them with each resource sample on its own connection (fixes a lock wait between crawl threads and metrics).
