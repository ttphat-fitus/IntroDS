# Data sources (Milestone 1)

Spec: https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling

## arXiv
| Purpose | Endpoint | Notes |
|---|---|---|
| Version list + dates | `https://oaipmh.arxiv.org/oai` (`ListRecords`, `metadataPrefix=arXivRaw`) | Resumption tokens expire daily; persist the token to resume. Old `export.arxiv.org/oai2` is retired. |
| Metadata lookup | `export.arxiv.org/api/query` (`id_list`) | `arxiv.py` 4 with `client.results(search)`. 100 IDs per request (~2 s). Versioned IDs return that version's `updated` date; missing IDs are simply absent. |
| Source download | `https://export.arxiv.org/src/{id}v{n}` | Never use `arxiv.org`. Gzipped tar, a single gzipped .tex, or a PDF (~3% have no source). |
| Rate limit | >= 3 s between calls, one connection at a time | Send a descriptive User-Agent. |

## Semantic Scholar
- `https://api.semanticscholar.org/graph/v1/paper/arXiv:{id}?fields=references.title,references.authors,references.year,references.publicationDate,references.externalIds`
- Flat field names only (`authors.name` is rejected).
- Unauthenticated: 1 req/s and 100 req / 5 min (HTTP 429 when exceeded). With a free API key: steady 1 req/s.
- Keep a reference in the final `references` table only if `externalIds.ArXiv` exists; keep old-style IDs (`hep-th/9901001`) as-is.
- New uploads may lag 1-7 days.
- Batch: `POST https://api.semanticscholar.org/graph/v1/paper/batch?fields=...` with `{"ids": ["arXiv:2601.08156", ...]}` (up to 500 IDs; we use 100 to keep responses small). Unknown IDs come back as `null`. Same reference lists as the single-paper endpoint (checked on 2601.08156: 23 references, 10 with arXiv ID).

## Measured on Colab (CPU runtime, 2026-10-23)
- Hardware: 2 vCPU Intel Xeon @ 2.20 GHz, 13.6 GB RAM, ~115 GB disk, Python 3.13. The account can also get a T4 GPU (free tier); L4/A100/H100 need Pro.
- 15 papers / 22 versions: 3.7 s per version on average (arXiv minimum is 3 s), 4.0 MB per paper before and 0.14 MB after figure removal.

## Open questions for the Lab Instructors
- Many sources ship `\bibitem`s only in a `.bbl` file, but the spec keeps only `.tex` and `.bib`. May we keep `.bbl`?
