# Guide: label your 10 papers (Milestone 3)

Each member labels **10 papers of their own ID range by hand** (team total: 50, the spec asks for at
least 25 papers and 500 entries). You decide, for 20 or more BibTeX entries of each paper, which crawled
reference it corresponds to. Plan about 2 hours.

The labels are the ground truth for training and for the MRR@5 evaluation, so label what you can verify
and skip what you cannot. Do not use an LLM, a search assistant or the automatic matcher to decide: the
automatic matcher is evaluated against your labels.

## 1. Set up

```bash
git clone https://github.com/ttphat-fitus/IntroDS && cd IntroDS
pip install -r src/requirements.txt
```

The team shares two Google Drive folders. Nothing in them is committed to GitHub.

| Folder | Content |
|---|---|
| [slices](https://drive.google.com/drive/folders/1qn16a7VkWK3DvZ49HXmRrjA6jIe-7YeE?usp=sharing) | `introds-<member>-slice.zip`: the tables of each member's range (the lead uploads) |
| [labels](https://drive.google.com/drive/folders/1yMr-4YnPiimikHqAHkaEDXNBlY0O3Emk?usp=sharing) | `labels-<member>.jsonl`: the manual labels (each member uploads their own) |

You need your member slice: a folder `data/<table>/*.parquet` with the tables of your range. Download
`introds-<member>-slice.zip` from the `slices` folder (about 220 MB) and unzip it:

```bash
unzip introds-m1-slice.zip -d slice      # creates slice/data/papers, slice/data/bibtex, ...
```

## 2. Build the labelling page

```bash
cd src
python -m introds label-prepare --member m1 --src ../slice --out ../labels/m1
```

It picks 10 papers (at least 20 BibTeX entries, 5 to 150 crawled references), samples 25 entries of each,
and writes two files. The pick is deterministic (seed 15), so the lead can rebuild it.

- `labels/<member>/label.html`: the labelling page, one file, no server, no internet needed.
- `labels/<member>/tasks.json`: the papers, entries and candidate references behind the page.

## 3. Label

Open `label.html` in a browser (double click). Pick a paper on the left, then an entry:

1. Read the entry (title, authors, year, venue, DOI, URL).
2. Find the reference it describes in the candidate list. Candidates are the references **of the same
   paper that Semantic Scholar resolved to an arXiv ID**; the likely ones are listed first, and the box
   filters by title, author or arXiv ID.
3. Click the candidate. The next unlabeled entry opens.

| Situation | Click |
|---|---|
| The entry and a candidate are the same work (a journal or conference version of a preprint counts) | that candidate |
| The entry is a real work but none of the candidates is it (book, website, paper without arXiv ID) | **No matching reference** |
| The entry is too damaged to judge (empty or garbled title, several entries merged) | **Skip** |

Rules of thumb:

- Match the work, not the version: same title and same first author, even if the year differs by one.
- A DOI or URL containing an arXiv ID is strong evidence. Titles that only share common words are not.
- When two candidates look equally good, open the arXiv link of the paper at the top of the page and
  read the reference in the PDF. If you still cannot tell, skip.
- **No matching reference is a normal and important answer.** Most entries have no arXiv candidate, so
  expect it often. Do not force a match.
- Each paper needs **at least 20 labeled entries**; skipped entries do not count. 25 are offered so you
  can skip a few.

Progress is saved in your browser. **Download labels** writes `labels-<member>.jsonl` (one JSON object
per entry: `arxiv_id`, `citation_key`, `groundtruth_arxiv_id` or `null`, `method`, `labeler`).
**Import** reloads a downloaded file, for example on another machine; skipped entries are not stored.

## 4. Check and send

```bash
python -m introds label-check ../labels/m1/labels-m1.jsonl --tasks ../labels/m1/tasks.json
```

It must end with `Labels are valid`: 10 papers, at least 20 labels each, every answer one of the
paper's candidates. Upload `labels-<member>.jsonl` to the
[labels](https://drive.google.com/drive/folders/1yMr-4YnPiimikHqAHkaEDXNBlY0O3Emk?usp=sharing) folder.
Labels are not committed to this repository.

## Which paper is test, validation or training?

`tasks.json` records it, the page does not show it: the first paper is the test paper, the second the
validation paper and the other eight are training papers. The split is the same for every member.
