# Data sources (Milestone 1)

Spec: https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling

## arXiv
| Purpose | Endpoint | Notes |
|---|---|---|
| Version list + dates | `https://oaipmh.arxiv.org/oai` (`ListRecords`, `metadataPrefix=arXivRaw`) | Resumption tokens expire daily; persist the token to resume. Old `export.arxiv.org/oai2` is retired. |
| Metadata lookup | `export.arxiv.org/api/query` (`id_list`) | Use `arxiv.py` >= 2 with `client.results(search)`. |
| Source download | `https://export.arxiv.org/src/{id}v{n}` | Never use `arxiv.org`. Gzipped tar, a single gzipped .tex, or a PDF (~3% have no source). |
| Rate limit | >= 3 s between calls, one connection at a time | Send a descriptive User-Agent. |

## Semantic Scholar
- `https://api.semanticscholar.org/graph/v1/paper/arXiv:{id}?fields=references.title,references.authors,references.year,references.publicationDate,references.externalIds`
- Flat field names only (`authors.name` is rejected).
- Unauthenticated: 1 req/s and 100 req / 5 min (HTTP 429 when exceeded). With a free API key: steady 1 req/s.
- Keep a reference in the final `references` table only if `externalIds.ArXiv` exists; keep old-style IDs (`hep-th/9901001`) as-is.
- New uploads may lag 1-7 days.

## Open questions for the Lab Instructors
- Many sources ship `\bibitem`s only in a `.bbl` file, but the spec keeps only `.tex` and `.bib`. May we keep `.bbl`?
