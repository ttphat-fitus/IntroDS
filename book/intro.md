# Introduction

Term project report of Group 15 for Introduction to Data Science (HCMUS).

The project crawls the full-text LaTeX sources of the arXiv papers assigned to the group, parses
every version into a hierarchical structure, and matches citations to the crawled reference
metadata with a machine learning pipeline evaluated by MRR@5.

| Milestone | Topic | Status |
|---|---|---|
| 1 | [Data crawling](./m1/crawling.ipynb) | Done: 25,000 papers, 31,756 versions, 100% success |
| 2 | [Hierarchical parsing and standardization](./m2/parsing.ipynb) | Done: 30,054 versions parsed (100%), 11.9M elements, 1.0M BibTeX entries |
| 3 | Reference matching pipeline | Not started |

## Team and ranges

Each member was assigned about 5,000 arXiv IDs.

| Member | Range | Papers | Versions |
|---|---|---|---|
| Nguyễn Cát Huy | 2610.02471 - 2610.07470 | 5,000 | 5,582 |
| Tiết Trọng Khiêm | 2608.29007 - 2609.02833 | 5,000 | 5,930 |
| Nguyễn Trực Phúc | 2607.18694 - 2607.23693 | 5,000 | 6,279 |
| Lê Kiến Quốc | 2607.08694 - 2607.13693 | 5,000 | 6,494 |
| Trịnh Tấn Phát | 2601.08156 - 2601.13155 | 5,000 | 7,471 |

## Links

- Source code: <https://github.com/ttphat-fitus/IntroDS>
- Dataset (Hugging Face, Parquet): [`ttphat/introds-arxiv`](https://huggingface.co/datasets/ttphat/introds-arxiv),
  currently the `papers`, `references`, `elements`, `hierarchy` and `bibtex` tables; it becomes
  public with Milestone 3.
- This report: <https://introds.opuslace.dev> (source: <https://github.com/ttphat-fitus/IntroDS-Book>)

## How this book is built

Every figure and table is generated when the book is built: the notebooks read the small
statistics files in `data/` (exported with `python -m introds stats`) and are executed by
`jupyter-book build --html --execute` in GitHub Actions. To re-run a notebook yourself, use the
**Run** (power) button at the top of a notebook page: it starts a kernel on
[mybinder.org](https://mybinder.org) with the packages of `requirements.txt` (the first start can
take a few minutes).
