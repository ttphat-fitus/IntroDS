# Guide: crawl your range on Google Colab (Milestone 1)

This guide is for members **m1, m2, m3 and m4**: each of you crawls your own range of arXiv IDs
with the notebook [`src/colab_crawl.ipynb`](../src/colab_crawl.ipynb). m5 is already done.
You do not need to install anything on your computer, and you do not need to change any code.

## 1. What you are going to run

| Member | Range |
|---|---|
| m1 | 2610.02471 - 2610.07470 |
| m2 | 2608.29007 - end of 2608, then 2609.00001 - 2609.02833 |
| m3 | 2607.18694 - 2607.23693 |
| m4 | 2607.08694 - 2607.13693 |

The notebook does everything end to end on a **CPU-only** Colab runtime (the benchmark
environment required by the course): it finds every version of every paper, downloads the LaTeX
sources from `export.arxiv.org` (keeping only `.tex` and `.bib`), fetches the references from
Semantic Scholar, measures time and memory, and writes the statistics for the report.

What to expect for one range (measured on m5):

| | |
|---|---|
| Running time | **7 - 11 hours**. arXiv allows one request every 3 seconds and a range has ~6,000-7,500 versions. |
| Google Drive space | **~1.2 - 1.7 GB** (your backup folder). Check that you have at least 2 GB free. |
| Colab disk | ~1.2 - 1.7 GB of the ~100 GB available. |
| RAM | ~250 MB. |

You need:

- a Google account with Colab access (the free tier is enough) and ~2 GB free on Google Drive;
- optionally, a [Semantic Scholar API key](https://www.semanticscholar.org/product/api#api-key-form).
  The crawl works without one; the key only makes the reference requests steadier.

## 2. Start the notebook

Pick **one** of the two ways below.

### Option A - Colab in the browser

1. Open
   <https://colab.research.google.com/github/ttphat-fitus/IntroDS/blob/main/src/colab_crawl.ipynb>
   (or in Colab: *File -> Open notebook -> GitHub*, paste the repository URL, pick
   `src/colab_crawl.ipynb`).
2. *Runtime -> Change runtime type* -> **CPU** -> *Save*.
3. Optional API key: click the **key icon** in the left sidebar -> *Add new secret* -> name
   `S2_API_KEY`, paste the key as value, and switch on **Notebook access**.
4. In the first code cell, set `MEMBER` to your range, for example `MEMBER = "m3"`.
   Leave `USE_DRIVE = True` and `LIMIT = None`.
5. *Runtime -> Run all*. When the Drive cell asks for permission, sign in with the same account
   and allow access.

### Option B - Colab extension for VS Code

1. Install the **Colab** extension (publisher: Google) in VS Code.
2. Clone the repository and open `src/colab_crawl.ipynb` in VS Code.
3. *Select Kernel* (top right) -> **Colab** -> **Auto Connect**, and sign in when asked.
   Auto Connect gives a CPU runtime, which is what we need.
4. Set `MEMBER` in the first code cell, then **Run All**.
5. The API key cell may not read Colab Secrets from VS Code. If a prompt appears, paste your key
   or press Enter to skip.
6. If the Drive cell fails, open the command palette (`Cmd/Ctrl+Shift+P`), run
   **Colab: Mount Google Drive to Server...**, then run the notebook again.

## 3. While it runs

- The crawl cell prints one progress line every 5 minutes, for example
  `[14:05:10] versions {'ok': 1520, 'no_tex': 61, 'pending': 4310} | s2 {'ok': 5000}`.
  `pending` goes down to 0; `s2` (references) finishes within the first minutes.
- **Keep the notebook open** (browser tab or VS Code window) and keep your computer awake.
  Colab shuts down a runtime when its notebook looks idle; a running cell counts as activity.
  If Colab asks whether you are still there, confirm.
- A backup is written to `MyDrive/introds-backup/<MEMBER>` every 20 minutes. **Do not delete or
  rename this folder.**
- Slow periods (several seconds per version, or `429` waits) are normal: arXiv sometimes
  throttles everyone. The crawler waits and retries by itself.

## 4. If the runtime disconnects

This will probably happen at least once: the free tier stops a runtime after at most 12 hours,
and sometimes earlier.

1. Reconnect (browser: *Reconnect*; VS Code: select the Colab kernel again).
2. Make sure `MEMBER` is still your range, then **Run all** again.

The Drive cell prints `Restored the previous progress from ...` and the crawl continues where
the last backup stopped (at most ~20 minutes of work is redone). Repeat as often as needed.

To stop on purpose, interrupt the crawl cell (*Runtime -> Interrupt execution*, or the stop
button). The crawler finishes the current download and exits cleanly; run all again later.

## 5. When it is done

The crawl cell ends with `crawl exited with code 0`, and the last cell prints the statistics
(papers found, success rate, sizes, running time, RAM). Check that:

- `pending` is gone from the last progress line;
- `paper_success_rate` is close to `1.0`.

Then send your results to the team lead:

1. In Google Drive, right-click `introds-backup/<MEMBER>` -> *Share* -> add the team lead as
   **Viewer**.
2. Post in the group chat: your member name, the last progress line, and the `summary.json` printed
   by the last cell.

The folder contains everything the lead needs: `crawl.sqlite` (state, metadata, references,
timings), `raw-*.tar` (your `.tex` / `.bib` files), `stats/` (report numbers),
`time_<MEMBER>_*.txt` (GNU time measurements) and `crawl_<MEMBER>.log`.

## 6. Troubleshooting

| Symptom | What to do |
|---|---|
| `crawl exited with code` other than 0 | Run all again: it resumes. If it fails at the same place twice, send the last 30 lines of the output to the lead. |
| `Restored ...` is not printed after a disconnect | Check that `MEMBER` is the same as before and that `MyDrive/introds-backup/<MEMBER>/crawl.sqlite` exists. |
| Drive full | Free some space (the backup needs ~2 GB), then run all again. |
| Many `failed` versions at the end | Run all again once: failed versions are retried up to three times. Versions answered with HTTP 404 are recorded as `missing`; that is expected for a few of them. |
| `S2_API_KEY` prompt keeps appearing | Press Enter to skip; the key is optional. |
| You want to try the notebook first | Set `LIMIT = 10` and `USE_DRIVE = False`, run all (a few minutes), then set them back and restart the runtime (*Runtime -> Disconnect and delete runtime*) before the real run. |

Please do not commit any data to the repository: data and backups stay on Drive.

## 7. For the team lead: merging the results

With each member's backup folder downloaded next to the code (for example `data/backup-m3/`):

```bash
cd src
INTRODS_DATA_DIR=../data/m3 python -m introds restore ../data/backup-m3
INTRODS_DATA_DIR=../data/m3 python -m introds stats --member m3 --out ../../introds-book/data/m1/m3
cp ../data/backup-m3/time_m3_*.txt ../../introds-book/data/m1/m3/

INTRODS_DATA_DIR=../data/all python -m introds merge ../data/m3/crawl.sqlite
cp -R ../data/m3/raw/ ../data/all/raw/
INTRODS_DATA_DIR=../data/all python -m introds stats --out ../../introds-book/data/m1/all
INTRODS_DATA_DIR=../data/all python -m introds export
```

The report notebook picks up every member folder under `introds-book/data/m1/` automatically.
