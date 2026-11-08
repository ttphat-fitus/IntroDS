# Hugging Face layout of the personal submissions

Every member submits **one public dataset on their own Hugging Face account**, holding only the tables
of their own ID range. This page fixes its structure so the five datasets can be checked and merged
the same way. The group-wide data stays with the lead.

## Repositories

| Repository | Visibility | Content | Submitted |
|---|---|---|---|
| `<user>/introds-<member>` (for example `ttphat/introds-m5`) | public | the six final tables of your range and the dataset card | yes |
| `<user>/introds-<member>-work` | private | anything else you want to keep (backups, intermediate files) | no |

Use exactly the name `introds-<member>` for the submitted dataset (`m1` .. `m5`). Keep raw TeX files, the
SQLite database, statistics, logs and labels **out of it**.

## Layout of the submitted dataset

```
<user>/introds-<member>
|-- README.md                  dataset card, YAML `configs` (one per table)
`-- data/
    |-- papers/*.parquet
    |-- references/*.parquet
    |-- elements/*.parquet
    |-- hierarchy/*.parquet
    |-- bibtex/*.parquet
    `-- predictions/*.parquet  Milestone 3
```

- Shards are named `part-00000.parquet`, `part-00001.parquet`, ... and stay below 1,000,000 rows.
- Columns, types and nullability follow the spec exactly; the card in [`publish.py`](../src/introds/publish.py)
  lists them. Strings that identify a row (`arxiv_id`, `element_id`, `citation_key`) are non-null.
- Only rows of your range: every `arxiv_id` is between your first and last ID.
- `predictions` holds one row per BibTeX entry of the papers of your range that belong to the training,
  validation or test set, and nothing else. `partition` is `train`, `valid` or `test`.
- No loading scripts. The card maps tables to files:

```yaml
configs:
  - config_name: papers
    data_files:
      - split: train
        path: data/papers/*.parquet
```

## Build it with one command

```bash
cd src
python -m introds publish --member m1 --src <folder with data/<table>/*.parquet> \
    --out ../data/publish/m1 --repo <user>/introds-m1 --public
```

The command writes the layout and the card, uploads with your `HF_TOKEN` (in `.env`, or Colab Secrets) and
replaces `data/*` and `README.md` of the repository. `--src` is the folder that holds your range as
`data/<table>/*.parquet`; the group dataset is private, so get your slice as described in
[guide-me-to-label.md](guide-me-to-label.md).

## Check before you submit

- [ ] The repository is public and the name is `introds-<member>`.
- [ ] `huggingface.co/datasets/<user>/introds-<member>/tree/main` shows only `README.md` and `data/`.
- [ ] Every table loads without a script:
  ```python
  from datasets import load_dataset

  for table in ["papers", "references", "elements", "hierarchy", "bibtex"]:
      row = next(iter(load_dataset("<user>/introds-m1", table, split="train", streaming=True)))
  ```
- [ ] Row counts match the card (`papers` = 5,000 for every member).
- [ ] The card links to the report: <https://ttphat-fitus.github.io/IntroDS-Book/>.
- [ ] After Milestone 3, `predictions` exists and the card lists it.
