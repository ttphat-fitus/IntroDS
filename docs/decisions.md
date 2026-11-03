# Design decisions

Short records of choices that are not obvious from the code. Newest first.
Format: date - decision - why - alternatives considered.

## 2026-10-30 - Milestone 2 interpretation of unspecified points
- **`.bbl` files** are fetched (`fetch-bbl`) for versions that have a `.bbl` but no `.bib` (2,913 versions, ~10% had no bibliography source at all) and used only to fill that gap. Result: all 2,913 fetched; versions without any bibliography source fell from 3,322 to 445 (1.5%).
- **Element kinds:** `document`, `heading`, `list`, `item`, `sentence`, `formula`, `figure`. Tables, algorithms and code listings are figures (the spec treats tables as figures).
- **Root edge:** every version has its own root (`#root1`, `#root2`, ... as in the spec example) whose `parent_id` is itself, because `parent_id` is non-null.
- **Levels** are relative to the sectioning commands a paper uses (no `\chapter` -> sections are level 1 under the root). The abstract and acknowledgements environments are top-level headings.
- **Lists:** `enumerate` and `description` are handled like `itemize`; list and item contents are their text so identical lists deduplicate.
- **References section** = `thebibliography`, `\bibliography` / `\printbibliography`, or a heading titled References / Bibliography; skipped with its subsections.
- **Bibliography scope:** from `.bib` files only cited keys are kept (BibTeX prints only those), unless `\nocite{*}`.
- **Reference identity:** same DOI, same normalized title (>= 12 alphanumerics), or same key. The latest version's key wins and fields are unioned latest-first (matches the spec's `vaswani2017` -> `vit_transformer` example). `\cite{}` keys are renamed before element deduplication, so sentences differing only by a renamed key merge.
- **Element identity:** exact match of (kind, cleaned content); duplicate edges within a version are dropped (the hierarchy table has no order column).
- **Root file ties:** prefer a file with `\begin{document}`, then main/ms/paper/manuscript/article.tex, then the most includes.
- **Macros** (`\newcommand`) are not expanded; `\makeatletter ... \makeatother` blocks are dropped as code.
- **Parser technology:** a regex/scanner pipeline instead of a TeX parser library (pylatexenc, TexSoup): it parses ~90 papers/s on 4 cores, and huge `.bib` files (one ships the 46 MB ACL Anthology) are indexed by key so only cited entries are parsed.

## 2026-10-24 - S3 bulk archive for the latest version of each paper
- **Why:** each monthly S3 tar holds one source per paper (`<yymm>/<id>.gz`, no version number) as of packing time. Streaming the tars that cover a range takes minutes (~85 MB/s from Colab), so only older versions and post-packing revisions go through export.arxiv.org's 3 s/request limit. The version is inferred as the latest one submitted before the member's mtime; `verify-s3` matched 15/15 samples file by file.
- **Result (m2):** 5,000 of 5,930 versions from S3 in 4.3 min, 930 from export in 61 min; 1 h 08 min end to end, against ~6-7 h export-only (m5).
- **Limits:** requester pays (~$1.5 for 17 GB); tars are added monthly, so the newest month (m1, 2610) is not available yet; needs AWS credentials (a user that can only assume a role with `s3:GetObject` on `arxiv/src/*`).

## 2026-10-24 - Crawl on Colab, supervise from a small EC2 instance
- **Why:** the benchmark environment is Colab CPU-only, so every request and measurement runs on Colab. The crawl runs inside the kernel (kernel BUSY) because Colab reclaims VMs whose kernel is idle (~90 min), which killed the first m5 run when it was detached with `nohup`. A supervisor on an always-on EC2 `t3.small` uses the `colab` CLI to mirror backups every 10 min and to recreate/restore the session after a reclaim or the 12 h free-tier limit.
- **Alternatives:** crawling on GCP/EC2 (measurements would not come from the required environment); supervising from a laptop (must stay on for hours).

## 2026-10-24 - Resume dropped downloads with HTTP Range
- **Why:** export.arxiv.org serves ~0.3-0.7 MB/s and cuts long transfers of large archives; 42 of 44 failures in the first m5 run were `IncompleteRead`. The server advertises `Accept-Ranges: bytes`, so a dropped transfer continues from the last byte received.
- **Note:** `gs://arxiv-dataset` only mirrors PDF/PS/HTML, not sources.

## 2026-10-23 - Discovery via arXiv API batches instead of OAI-PMH
- **Why:** the API accepts versioned IDs (`2601.08157v2`) and returns that version's date, so two batched passes give every version date. 5,000 IDs take ~100 requests (~2 min) instead of a full OAI-PMH sweep of everything modified since January.
- **Alternatives:** OAI-PMH `arXivRaw` (complete version list, but sweeps far more records than we need).
- **Supersedes:** the 2026-10-15 OAI-PMH decision below.

## 2026-10-23 - Semantic Scholar batch endpoint
- **Why:** `POST /paper/batch` returns references for 100 papers per request (verified identical to the single-paper endpoint), so 5,000 papers need ~50 requests instead of 5,000.

## 2026-10-23 - Sources and references in parallel threads
- **Why:** different hosts with independent rate limits; the arXiv download stage (>= 3 s per version) is the bottleneck, so references add almost no wall time.

## 2026-10-23 - Paper size "before figure removal" = uncompressed archive contents
- **Why:** comparable with the "after" size (uncompressed `.tex`/`.bib`). The compressed download size is recorded too (`bytes_download`).

## 2026-10-15 - SQLite for state, filesystem for TeX sources
- **Why:** single file, stdlib, works on Colab, makes every command resumable via `status` columns; TeX files stay on disk with their original relative paths so Milestone 2 can resolve `\input`.
- **Alternatives:** Postgres (needs a server, overkill), JSON files per paper (hard to query, no atomic updates).

## 2026-10-15 - Extract tarballs in memory, write only .tex/.bib
- **Why:** spec requires removing figures by extraction; never writing the full tarball keeps disk usage small and still lets us record `bytes_unpacked` (size before figure removal).

## 2026-10-15 - Discovery via OAI-PMH `arXivRaw` (superseded)
- **Why:** one sweep (`from=2026-01-01`) returns every version with its date, needed for `submission_date` / `revised_dates`; per-ID API calls at 3 s each would take ~21 h for 25k IDs.
- **Alternatives:** arXiv API `id_list` batches (fast, but only first/last dates), Kaggle snapshot (may lag behind recent IDs).

## 2026-10-15 - Each member crawls their own range on their own Colab
- **Why:** ~37k source downloads x 3 s = ~31 h for one client; splitting by member keeps each run ~6-7 h and within one Colab session. Per-member SQLite files are merged before export.

## 2026-10-15 - Two repositories
- **Why:** spec requires the Jupyter Book in a separate public repository. The crawler exports small summary files into the book repo's `data/` so figures are generated at build time.
