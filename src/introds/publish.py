"""Publish one member's slice of the dataset: keep the rows of the member's ID range, write the
dataset card and optionally upload everything to a Hugging Face dataset repository."""

import shutil
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from . import ranges

TABLES = ("papers", "references", "elements", "hierarchy", "bibtex")
ROWS_PER_SHARD = 1_000_000

CARD = """---
pretty_name: introDS Group 15 - arXiv papers {first}..{last} ({member})
language:
  - en
tags:
  - arxiv
  - citations
  - latex
  - entity-resolution
configs:
{configs}---

# introDS Group 15 - arXiv dataset, range of {member}

Slice of the Introduction to Data Science term project (HCMUS) of Group 15, built with
[`introds`](https://github.com/ttphat-fitus/IntroDS). Report: <https://ttphat-fitus.github.io/IntroDS-Book/>.

It covers the arXiv papers `{first}` to `{last}` ({n_papers:,} papers), every version of each paper,
and their references from Semantic Scholar.

| Table | Rows | Content | Milestone |
|---|---|---|---|
{rows}| `predictions` | - | Reference matching results (top-5 candidates) | 3 (to come) |

## Schemas

**papers**: `arxiv_id` (string, non-null), `title` (string), `authors` (list of strings),
`submission_date` (ISO 8601 string, date of v1), `revised_dates` (list of strings, dates of v2..vn),
`venue` (string, nullable; arXiv journal-ref, else Semantic Scholar venue).

**references**: `arxiv_id` (string, non-null, citing paper), `ref_arxiv_id` (string, non-null),
`ref_title` (string), `ref_authors` (list of strings), `ref_submission_date` (string),
`ref_s2_id` (string, Semantic Scholar paper ID). Only references that have an arXiv ID.

**elements**: `element_id` (string, non-null, `<yymm-nnnnn>#<prefix><n>`), `arxiv_id` (string,
non-null), `kind` (dictionary: `document`, `heading`, `list`, `item`, `sentence`, `formula`, `figure`),
`content` (string; cleaned LaTeX, inline math as `$...$`, block math as `\\begin{{equation}}...`).
Elements whose cleaned content is identical across versions share one ID.

**hierarchy**: `arxiv_id` (string, non-null), `version` (int), `element_id` (string, non-null),
`parent_id` (string, non-null). Each version has its own root (`#root1`, `#root2`, ...), whose parent
is itself.

**bibtex**: `arxiv_id`, `citation_key` (non-null), `entry_type` (dictionary), `title`, `authors`
(list of strings), `year` (int, nullable), `doi`, `journal`, `url`. One row per reference after
deduplication across versions; `\\cite{{}}` keys in `elements` use these keys.

## Usage

```python
from datasets import load_dataset

papers = load_dataset("{repo}", "papers", split="train")
elements = load_dataset("{repo}", "elements", split="train", streaming=True)
```
"""


def in_span(arxiv_id, member):
    yymm, number = arxiv_id.split(".")
    return any(
        s.yymm == yymm and int(number) >= s.first and (s.last is None or int(number) <= s.last)
        for s in ranges.spans(member)
    )


def _slice(files, ids, target):
    """Write the rows of `files` whose arxiv_id is in `ids` as shards of ROWS_PER_SHARD rows."""
    parts = [pq.read_table(f, filters=[("arxiv_id", "in", ids)]) for f in files]
    table = pa.concat_tables([t for t in parts if t.num_rows]).unify_dictionaries()
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    starts = range(0, table.num_rows, ROWS_PER_SHARD)
    for i, start in enumerate(starts):
        pq.write_table(table.slice(start, ROWS_PER_SHARD), target / f"part-{i:05d}.parquet")
    return table.num_rows, len(starts)


def build(src, member, out, repo):
    """Slice the five tables of `src/data/<table>/*.parquet` into `out`; returns rows per table."""
    src, out = Path(src), Path(out)
    files = {t: sorted((src / "data" / t).glob("*.parquet")) for t in TABLES}
    missing = [t for t, f in files.items() if not f]
    if missing:
        raise SystemExit(f"No Parquet shards in {src}/data for: {', '.join(missing)}")
    papers = pa.concat_tables([pq.read_table(f, columns=["arxiv_id"]) for f in files["papers"]])
    ids = [a for a in papers["arxiv_id"].to_pylist() if in_span(a, member)]
    counts = {}
    for table in TABLES:
        counts[table] = _slice(files[table], ids, out / "data" / table)
        print(f"{table}: {counts[table][0]:,} rows in {counts[table][1]} shard(s)", flush=True)
    _, start_month, start_id, end_month, end_id = next(
        a for a in ranges.ASSIGNMENTS if a[0] == member
    )
    first = ranges.arxiv_id(ranges._yymm(start_month), start_id)
    last = ranges.arxiv_id(ranges._yymm(end_month), end_id)
    contents = {
        "papers": "Crawled paper metadata | 1",
        "references": "Crawled references that have an arXiv ID, one row per (citing paper, reference) | 1",
        "elements": "Deduplicated parsed elements across versions | 2",
        "hierarchy": "Per-version node-parent edges | 2",
        "bibtex": "Unified BibTeX entries after deduplication | 2",
    }
    rows = "".join(f"| `{t}` | {counts[t][0]:,} | {contents[t]} |\n" for t in TABLES)
    configs = "".join(
        f"  - config_name: {t}\n    data_files:\n      - split: train\n        path: data/{t}/*.parquet\n"
        for t in TABLES
    )
    (out / "README.md").write_text(
        CARD.format(
            member=member,
            first=first,
            last=last,
            n_papers=counts["papers"][0],
            rows=rows,
            configs=configs,
            repo=repo,
        )
    )
    return counts


def upload(out, repo, private=True):
    from huggingface_hub import HfApi

    from . import config  # loads HF_TOKEN from .env

    api = HfApi(token=config.get_secret("HF_TOKEN"))
    api.create_repo(repo, repo_type="dataset", private=private, exist_ok=True)
    api.upload_folder(
        repo_id=repo,
        repo_type="dataset",
        folder_path=str(out),
        delete_patterns=["data/*", "README.md"],
        commit_message="data: milestone 1-2 tables of the member's ID range",
    )
    api.update_repo_settings(repo, repo_type="dataset", private=private)
