# introDS

Report (Jupyter Book): <GitHub Pages link>

## Environment

- Python 3.12+ (benchmarked on Google Colab, CPU only)
- Install dependencies:

```bash
pip install -r src/requirements.txt
cp .env.example .env   # fill in S2_API_KEY, HF_TOKEN
```

On Colab, use Secrets (key icon) instead of `.env`, named `S2_API_KEY` and `HF_TOKEN`.

## Contributing

`main` is protected: create a branch, open a pull request, and it is squash-merged.
Commit messages and PR titles must follow [Conventional Commits](https://www.conventionalcommits.org):

```
feat(crawl): download sources via export.arxiv.org
fix(s2): back off on HTTP 429
docs: add M1 statistics to changelog
```

Allowed types: `feat fix docs style refactor perf test build ci chore revert`. Install the local hooks once per clone:

```bash
pip install pre-commit   # or: uv tool install pre-commit
pre-commit install
```

## Usage

Run from `src/`. Data goes to `data/` at the repository root, or to `$INTRODS_DATA_DIR`.

```bash
cd src
python -m introds spans --member m5                  # show the assigned ID spans
python -m introds crawl --member m5 \
    --backup-dir /content/drive/MyDrive/introds-backup/m5   # discover + sources + references
python -m introds stats --member m5 --out ../../introds-book/data/m1
python -m introds export                             # Parquet tables + metadata.json per paper
```

`crawl` runs entry discovery (arXiv API), then downloads sources (export.arxiv.org) and references
(Semantic Scholar) concurrently. The stages are also available alone: `discover`, `fetch-src`,
`fetch-refs`. Useful flags: `--keep-bbl` (also keep `.bbl` files), `--retry-not-found`
(re-query papers Semantic Scholar did not know yet), `--limit N` (first N IDs per span, for tests).

Every command is resumable: if interrupted, rerun the same command. With `--backup-dir`, an
incremental backup is written every 20 minutes; `python -m introds restore <dir>` rebuilds the
data directory from it. `python -m introds merge a.sqlite b.sqlite` merges members' databases.

On Google Colab, use [`src/colab_crawl.ipynb`](src/colab_crawl.ipynb): it mounts Drive, restores
the latest backup, runs the crawl inside the notebook, and writes statistics at the end.
Step-by-step instructions for team members: [`docs/guideme.md`](docs/guideme.md).

## Output

```
data/
  crawl.sqlite                 crawl state, metadata, references, timings, resource samples
  raw/2601-08157/
    v1/ v2/ v3/                .tex / .bib files of each version, original relative paths
    metadata.json              title, authors, dates, venue, per-version status
    references.json            every Semantic Scholar reference (with or without arXiv ID)
  hf/data/papers/*.parquet     final dataset tables (Hugging Face layout)
  hf/data/references/*.parquet
```

## Layout

```
src/
  requirements.txt
  colab_crawl.ipynb  run one member's crawl on Colab
  introds/
    __main__.py    CLI
    config.py      configuration, secret loading
    ranges.py      assigned arXiv ID ranges
    db.py          SQLite schema, merging
    discover.py    entry discovery (arXiv API, batched)
    sources.py     source download + .tex/.bib extraction
    refs.py        Semantic Scholar references (batch API)
    http.py        HTTP session, retry with backoff
    ratelimit.py   per-host rate limiter
    metrics.py     timing, RAM and disk measurement
    backup.py      incremental backup / restore
    stats.py       report statistics
    export.py      Parquet tables, per-paper metadata files
docs/
  CHANGELOG.md     changes per milestone
  decisions.md     design decisions and their rationale
  research/        notes on data sources and techniques
```
