"""Tests of the Milestone 2 parser on small LaTeX snippets. Run: python -m pytest tests"""

import gzip
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from introds import bibliography as bib
from introds import latex, structure

# ---------------------------------------------------------------- multi-file gathering


def test_comments_are_removed_but_escaped_percent_is_kept():
    text = "a 50\\% gain % a comment\n% \\input{hidden}\nb"
    assert latex.strip_comments(text) == "a 50\\% gain \n\nb"


def test_gather_follows_inputs_transitively_and_skips_commented_and_missing_files():
    sources = {
        "main.tex": latex.strip_comments(
            "\\documentclass{article}\\begin{document}\\input{sec/intro}\n"
            "% \\input{sec/old}\n\\include{missing}\\end{document}"
        ),
        "sec/intro.tex": "Intro \\input{sec/deep}",
        "sec/deep.tex": "Deep \\input{sec/intro}",  # cycle
        "sec/old.tex": "never included",
    }
    text, used = latex.gather(sources, "main.tex")
    assert used == ["main.tex", "sec/intro.tex", "sec/deep.tex"]
    assert "Intro" in text and "Deep" in text and "never included" not in text


def test_root_is_the_file_opening_the_document_when_the_class_is_in_a_preamble():
    sources = {
        "preamble.tex": "\\documentclass{article}\\usepackage{x}",
        "main.tex": "\\input{preamble}\\begin{document}Text.\\end{document}",
    }
    assert latex.find_root(None, sources) == "main.tex"


def test_bare_carriage_returns_are_line_breaks(tmp_path):
    f = tmp_path / "old.tex"
    f.write_bytes(b"\\documentclass{article}% comment\rBody text.")
    assert latex.strip_comments(latex.read_text(f)) == "\\documentclass{article}\nBody text."


def test_input_paths_with_macros_are_resolved():
    sources = {
        "main.tex": "\\newcommand{\\SEC}{chapters}\\begin{document}\\input{\\SEC/intro}\\end{document}",
        "chapters/intro.tex": "Introduction text",
    }
    _, used = latex.gather(sources, "main.tex")
    assert used == ["main.tex", "chapters/intro.tex"]


def test_begin_document_inside_a_macro_definition_is_not_the_body():
    text = "\\def\\bd{\\begin{document}}\\def\\ed{\\end{document}}\n\\begin{document}Body.\\end{document}"
    assert latex.split_document(text)[1] == "Body."


def test_root_is_the_documentclass_file_with_a_document_body():
    sources = {
        "macros.tex": "\\newcommand{\\x}{y}",
        "standalone.tex": "\\documentclass{standalone}\\input{fig}",
        "paper.tex": "\\documentclass{article}\\begin{document}x\\end{document}",
    }
    assert latex.find_root(None, sources) == "paper.tex"


# ---------------------------------------------------------------- standardization


def test_block_and_inline_math_are_normalized():
    out = latex.normalize_math(
        "A \\(x\\) and $$y=1$$ and \\[z\\label{e}\\] then \\begin{align*}a&=b\\\\c&=d\\end{align*}"
    )
    assert "$x$" in out
    assert "\\begin{equation}y=1\\end{equation}" in out
    assert "\\begin{equation}z\\end{equation}" in out
    assert "\\begin{equation}\\begin{aligned}a&=b\\\\c&=d\\end{aligned}\\end{equation}" in out


def test_cleanup_drops_formatting_and_unwraps_emphasis():
    out = latex.cleanup(
        "\\begin{figure}[htpb]\\centering\\midrule\\vspace{2mm} \\textbf{bold} \\label{x}"
    )
    assert out.startswith("\\begin{figure}") and "[htpb]" not in out
    for gone in ("\\centering", "\\midrule", "\\vspace", "\\label", "\\textbf"):
        assert gone not in out
    assert "bold" in out


@pytest.mark.parametrize(
    "text, expected",
    [
        ("We use e.g. trees. They work.", 2),
        ("As shown by Smith et al. the gain is 3.5 points. Next.", 2),
        ("See Fig. 1 for details. Then Table 2.", 2),
        ("The value $a. B$ holds. Done.", 2),
        ("Code is at https://x.org/a.b. More text.", 2),
        ("Prior work \\cite{a.b, c.d} exists. Yes.", 2),
        ("i.e. this is one sentence.", 1),
    ],
)
def test_sentence_splitting(text, expected):
    assert len(structure.split_sentences(text)) == expected


# ---------------------------------------------------------------- hierarchy


def _tree(body):
    nodes = structure.build(latex.cleanup(latex.normalize_math(body)), "doc (v1)")
    return [(kind, content, parent) for kind, content, parent in nodes]


def test_levels_are_dynamic_and_references_are_skipped_but_appendix_kept():
    nodes = _tree(
        "\\begin{abstract}Short abstract.\\end{abstract}"
        "\\section{Intro}First sentence. Second one."
        "\\subsection{Details}\\begin{itemize}\\item One point.\\item Two points.\\end{itemize}"
        "\\begin{equation}E=mc^2\\end{equation}"
        "\\section*{References}Smith 2020. Jones 2021."
        "\\appendix\\section{Proofs}Proof text."
    )
    headings = {content: i for i, (kind, content, _) in enumerate(nodes) if kind == "heading"}
    assert set(headings) == {"Abstract", "Intro", "Details", "Proofs"}
    assert nodes[headings["Details"]][2] == headings["Intro"]  # subsection under section
    assert nodes[headings["Intro"]][2] == 0  # section under the root
    assert not any("Smith" in c for _, c, _ in nodes)  # references skipped
    kinds = [k for k, _, _ in nodes]
    assert kinds.count("item") == 2 and kinds.count("formula") == 1
    items = [c for k, c, _ in nodes if k == "item"]
    assert items == ["One point.", "Two points."]


def test_floats_are_single_figure_leaves():
    nodes = _tree(
        "\\section{A}\\begin{table}[h]\\centering\\begin{tabular}{c}x\\end{tabular}\\end{table}"
    )
    figures = [c for k, c, _ in nodes if k == "figure"]
    assert len(figures) == 1 and figures[0].startswith("\\begin{table}")


# ---------------------------------------------------------------- bibliography


def test_bib_parsing_keeps_cited_entries_only():
    text = (
        "@article{a, title={Attention Is All You Need}, author={Vaswani, Ashish and Shazeer, Noam},"
        " year=2017, doi={10.5555/1234}}\n@misc{b, title={Unused}}"
    )
    entries = bib.parse_bib(text, keys={"a"})
    assert list(entries) == ["a"]
    row = bib.from_bib_fields("a", entries["a"])
    assert row["authors"] == ["Ashish Vaswani", "Noam Shazeer"] and row["year"] == 2017


def test_bibitem_is_converted_to_bibtex_fields():
    text = (
        "\\begin{thebibliography}{1}\\bibitem[{Vaswani et~al.(2017)}]{vaswani2017} "
        "A.~Vaswani, N.~Shazeer, and N.~Parmar.\\newblock Attention is all you need."
        "\\newblock In \\emph{NeurIPS}, 2017. arXiv:1706.03762\\end{thebibliography}"
    )
    (entry,) = bib.parse_bibitems(text, "bibitem")
    assert entry["key"] == "vaswani2017"
    assert entry["title"] == "Attention is all you need"
    assert entry["year"] == 2017 and entry["entry_type"] == "inproceedings"
    assert entry["url"] == "https://arxiv.org/abs/1706.03762"
    assert len(entry["authors"]) == 3


def test_clean_value_keeps_commands_starting_with_accent_letters():
    assert (
        bib.clean_value("\\textbf{Deep} nets \\\\ at \\url{x}, Caf\\'{e}") == "Deep nets at x, Cafe"
    )


def test_revtex_bibinfo_entries():
    text = (
        "\\bibitem [{Li(2024)}]{li2024}\\bibfield {author} {\\bibinfo {author} {\\bibfnamefont {Y.}"
        "~\\bibnamefont {Li}}},\\ \\bibinfo {title} {Quantum widgets},\\ \\bibinfo {journal}"
        " {Phys. Rev. A} \\textbf {\\bibinfo {volume} {1}} (\\bibinfo {year} {2024})"
    )
    (entry,) = bib.parse_bibitems(text, "bbl")
    assert entry["title"] == "Quantum widgets" and entry["authors"] == ["Y. Li"]
    assert (
        entry["journal"] == "Phys. Rev. A"
        and entry["year"] == 2024
        and entry["entry_type"] == "article"
    )


def test_biblatex_bbl_entries():
    text = (
        "\\entry{vit}{article}{}\\name{author}{1}{}{{{hash=1}{family={Dosovitskiy},"
        " familyi={D.}, given={Alexey}, giveni={A.}}}}\\field{title}{An Image is Worth 16x16 Words}"
        "\\field{year}{2021}\\verb{doi}\n\\verb 10.1/vit\n\\endverb\\endentry"
    )
    (entry,) = bib.parse_biblatex_bbl(text)
    assert entry["authors"] == ["Alexey Dosovitskiy"] and entry["doi"] == "10.1/vit"


# ---------------------------------------------------------------- deduplication


def test_reference_deduplication_follows_the_spec_example():
    from introds.parser import dedup_references, rename_cites

    base = {"entry_type": "article", "authors": ["A. Vaswani"], "journal": None, "url": None}
    title = "Attention is all you need"
    per_version = {
        1: [{**base, "key": "vaswani2017", "title": title, "year": 2017, "doi": None}],
        2: [{**base, "key": "vit_transformer", "title": title, "year": 2017, "doi": "10.1/x"}],
        3: [{**base, "key": "vit_transformer", "title": title, "year": None, "doi": None}],
    }
    unified, rename = dedup_references(per_version)
    assert len(unified) == 1
    entry = unified[0]
    assert entry["key"] == "vit_transformer" and entry["year"] == 2017 and entry["doi"] == "10.1/x"
    assert rename_cites("see \\citep[p.~2]{vaswani2017, other}", rename[1]) == (
        "see \\citep[p.~2]{vit_transformer,other}"
    )


def test_parse_paper_shares_identical_elements_across_versions(tmp_path, monkeypatch):
    from introds import config, parser

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "RAW_DIR", tmp_path / "raw")
    doc = (
        "\\documentclass{{article}}\\begin{{document}}\\section{{Intro}}{sentence}"
        " We cite \\cite{{{key}}}.\\bibliography{{refs}}\\end{{document}}"
    )
    bibtex = "@misc{{{key}, title={{A Shared Reference Title}}, year=2020}}"
    for v, (sentence, key) in enumerate([("Same sentence.", "old"), ("Same sentence.", "new")], 1):
        d = tmp_path / "raw" / "2601-00001" / f"v{v}"
        d.mkdir(parents=True)
        (d / "main.tex").write_text(doc.format(sentence=sentence, key=key))
        (d / "refs.bib").write_text(bibtex.format(key=key))

    _, paper, infos = parser.parse_paper(("2601.00001", [(1, "ok"), (2, "ok"), (3, "no_tex")]))
    assert infos[3]["status"] == "empty" and paper["n_versions_parsed"] == 2
    payload = json.loads(gzip.decompress((tmp_path / "parsed" / "2601-00001.json.gz").read_bytes()))
    edges = payload["hierarchy"]
    roots = {e for v, e, p in edges if e == p}
    assert roots == {"2601-00001#root1", "2601-00001#root2"}  # one root per version
    shared = {e for v, e, _ in edges if v == 1} & {e for v, e, _ in edges if v == 2}
    contents = {e: c for e, _, c in payload["elements"]}
    assert any(contents[e] == "Same sentence." for e in shared)
    assert any(contents[e] == "We cite \\cite{new}." for e in shared)  # key renamed, then merged
    assert [b["key"] for b in payload["bibtex"]] == ["new"]
