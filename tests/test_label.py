"""Tests of the Milestone 3 labelling tools on a tiny synthetic slice. Run: python -m pytest tests"""

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from introds import label

IDS = [f"2601.0815{i}" for i in range(6, 10)]


def _slice(root):
    tables = {
        "papers": [{"arxiv_id": a, "title": f"Paper {a}"} for a in IDS],
        "bibtex": [
            {
                "arxiv_id": a,
                "citation_key": f"k{j:02d}",
                "entry_type": "article",
                "title": f"Title {j}",
                "authors": ["A B"],
                "year": 2020,
                "journal": None,
                "doi": None,
                "url": None,
            }
            for a in IDS
            for j in range(22)
        ],
        "references": [
            {
                "arxiv_id": a,
                "ref_arxiv_id": f"2001.0000{j}",
                "ref_title": f"Title {j}",
                "ref_authors": ["A B"],
                "ref_submission_date": "2020-01-01",
            }
            for a in IDS
            for j in range(6)
        ],
    }
    for name, rows in tables.items():
        folder = root / "data" / name
        folder.mkdir(parents=True)
        pd.DataFrame(rows).to_parquet(folder / "part-0.parquet")


def test_prepare_and_check(tmp_path):
    _slice(tmp_path / "src")
    tasks, pool = label.prepare(tmp_path / "src", "m5", tmp_path / "out", papers=3, per_paper=21)
    assert pool == 4 and len(tasks["papers"]) == 3
    assert [p["partition"] for p in tasks["papers"]] == ["test", "valid", "train"]
    assert all(len(p["entries"]) == 21 and len(p["refs"]) == 6 for p in tasks["papers"])
    page = (tmp_path / "out" / "label.html").read_text()
    assert "__DATA__" not in page and tasks["papers"][0]["arxiv_id"] in page

    rows = [
        {"arxiv_id": p["arxiv_id"], "citation_key": e["citation_key"], "method": "manual"}
        | {"groundtruth_arxiv_id": p["refs"][0]["ref_arxiv_id"] if i % 2 else None, "labeler": "m5"}
        for p in tasks["papers"]
        for i, e in enumerate(p["entries"][:20])
    ]
    path = tmp_path / "labels.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows))
    problems, summary = label.check(path, tmp_path / "out" / "tasks.json")
    assert problems == [] and summary["labels"] == 60 and summary["no_match_share"] == 0.5

    rows[0]["groundtruth_arxiv_id"] = "1999.99999"
    path.write_text("\n".join(json.dumps(r) for r in rows[:-1]))
    problems, _ = label.check(path, tmp_path / "out" / "tasks.json")
    assert len(problems) == 2
