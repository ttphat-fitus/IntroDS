# Design decisions

Short records of choices that are not obvious from the code. Newest first.
Format: date - decision - why - alternatives considered.

## 2026-10-15 - SQLite for state, filesystem for TeX sources
- **Why:** single file, stdlib, works on Colab, makes every command resumable via `status` columns; TeX files stay on disk with their original relative paths so Milestone 2 can resolve `\input`.
- **Alternatives:** Postgres (needs a server, overkill), JSON files per paper (hard to query, no atomic updates).

## 2026-10-15 - Extract tarballs in memory, write only .tex/.bib
- **Why:** spec requires removing figures by extraction; never writing the full tarball keeps disk usage small and still lets us record `bytes_raw` (size before figure removal).

## 2026-10-15 - Discovery via OAI-PMH `arXivRaw`
- **Why:** one sweep (`from=2026-01-01`) returns every version with its date, needed for `submission_date` / `revised_dates`; per-ID API calls at 3 s each would take ~21 h for 25k IDs.
- **Alternatives:** arXiv API `id_list` batches (fast, but only first/last dates), Kaggle snapshot (may lag behind recent IDs).

## 2026-10-15 - Each member crawls their own range on their own Colab
- **Why:** ~37k source downloads x 3 s = ~31 h for one client; splitting by member keeps each run ~6-7 h and within one Colab session. Per-member SQLite files are merged before export.

## 2026-10-15 - Two repositories
- **Why:** spec requires the Jupyter Book in a separate public repository. The crawler exports small summary files into the book repo's `data/` so figures are generated at build time.
