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

```bash
cd src
python -m introds init-db
python -m introds spans --member m1
python -m introds discover   --member m1
python -m introds fetch-src  --member m1
python -m introds fetch-refs --member m1
python -m introds stats
```

Every command is resumable: if interrupted (e.g. the Colab session ends), rerun the same command.

## Layout

```
src/
  requirements.txt
  introds/
    config.py      configuration, secret loading
    ranges.py      assigned arXiv ID ranges
    db.py          SQLite schema (crawl state + metadata)
    metrics.py     timing, RAM and disk measurement
    ratelimit.py   per-host rate limiter
docs/
  CHANGELOG.md     changes per milestone
  decisions.md     design decisions and their rationale
  research/        notes on data sources and techniques
data/              (not committed) raw/<yymm-nnnnn>/v<k>/..., crawl.sqlite
```
