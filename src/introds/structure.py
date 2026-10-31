"""Hierarchy construction for Milestone 2.

The flattened, cleaned body of a version becomes a tree:

    document
      heading (chapter / section / subsection / ... ; levels are assigned dynamically)
        sentence | formula | figure | list
                                       item
                                         sentence | formula | figure | list ...

Floats (figure, table, algorithm, code listings) are single `figure` leaves, block math is a
`formula` leaf, prose is split into `sentence` leaves. The references section is skipped;
abstract, acknowledgements and appendices are kept.
"""

import re

from .latex import find_env_end, normalize_space, read_group

SECTIONING = [
    "part",
    "chapter",
    "section",
    "subsection",
    "subsubsection",
    "paragraph",
    "subparagraph",
]
LISTS = {
    "itemize",
    "enumerate",
    "description",
    "compactitem",
    "compactenum",
    "inparaenum",
    "asparaenum",
    "outline",
}
FLOATS = {
    "figure",
    "figure*",
    "table",
    "table*",
    "wrapfigure",
    "wraptable",
    "sidewaysfigure",
    "sidewaystable",
    "algorithm",
    "algorithm*",
    "algorithmic",
    "lstlisting",
    "verbatim",
    "minted",
    "tabular",
    "tabular*",
    "tabularx",
    "longtable",
    "tikzpicture",
    "subfigure",
    "SCfigure",
}
HEADING_ENVS = {
    "abstract": "Abstract",
    "acknowledgments": "Acknowledgments",
    "acknowledgements": "Acknowledgements",
    "acknowledgment": "Acknowledgment",
    "acknowledgement": "Acknowledgement",
}
SKIP_ENVS = {"thebibliography", "references", "titlepage", "CCSXML", "teaserfigure"}
_REFERENCE_TITLES = re.compile(
    r"^\s*(references?|bibliography|literature cited|works cited)\s*$", re.IGNORECASE
)

_TOKEN = re.compile(
    r"\\(?:"
    r"(part|chapter|section|subsection|subsubsection|paragraph|subparagraph)(\*?)(?![A-Za-z])"
    r"|begin\{([^}]+)\}"
    r"|end\{([^}]+)\}"
    r"|(item)(?![A-Za-z])"
    r"|(acknowledgments|acknowledgements)(?![A-Za-z])"
    r")"
)

# ---------------------------------------------------------------- sentence splitting

_PROTECTED = re.compile(
    r"\$[^$]*\$"  # inline math
    r"|\\[A-Za-z]+\*?(?:\s*\[[^\]]*\])*(?:\s*\{(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\})*"  # commands
    r"|(?:https?://|www\.)\S*[^\s.,;:!?)]"  # URLs
    r"|\d+\.\d+"  # decimals
)
_ABBREVIATIONS = {
    "e.g",
    "i.e",
    "et al",
    "al",
    "fig",
    "figs",
    "eq",
    "eqs",
    "eqn",
    "sec",
    "secs",
    "sect",
    "tab",
    "tbl",
    "ref",
    "refs",
    "cf",
    "vs",
    "resp",
    "approx",
    "no",
    "nos",
    "dr",
    "prof",
    "mr",
    "mrs",
    "ms",
    "jr",
    "st",
    "thm",
    "lem",
    "def",
    "prop",
    "cor",
    "alg",
    "ch",
    "app",
    "appx",
    "viz",
    "ca",
    "vol",
    "pp",
    "ed",
    "eds",
    "inc",
    "ltd",
    "co",
    "dept",
    "univ",
    "w.r.t",
    "a.k.a",
    "esp",
    "incl",
    "equ",
    "jan",
    "feb",
    "mar",
    "apr",
    "jun",
    "jul",
    "aug",
    "sep",
    "sept",
    "oct",
    "nov",
    "dec",
    "est",
}
_WORD_BEFORE = re.compile(r"([A-Za-z][A-Za-z.]*)$")
_STARTS_SENTENCE = re.compile(r"\s+(?=[A-Z0-9\\$(\[`\"'])")


def split_sentences(text):
    """Split prose at . ! ? that end a sentence, never inside math, commands, URLs, decimals or
    abbreviations (i.e., e.g., et al., Fig. 1, ...)."""
    protected = [
        (m.start(), m.end()) for m in _PROTECTED.finditer(text) if m.end() - m.start() <= 300
    ]
    cuts, p = [], 0
    for m in re.finditer(r"[.!?]+[\"')\]]*", text):
        i = m.start()
        while p < len(protected) and protected[p][1] <= i:
            p += 1
        if p < len(protected) and protected[p][0] <= i < protected[p][1]:
            continue  # inside math / a command / a URL / a decimal
        nxt = _STARTS_SENTENCE.match(text, m.end())
        if not nxt and m.end() < len(text):
            continue  # not followed by whitespace + a sentence start
        right_after_atom = p > 0 and protected[p - 1][1] == i  # e.g. a URL or $x$ ends here
        if text[i] == "." and not right_after_atom:
            word = _WORD_BEFORE.search(text[max(0, i - 40) : i])
            if word:
                w = word.group(1).lower().rstrip(".")
                if w in _ABBREVIATIONS or len(w) == 1 or re.fullmatch(r"(?:[a-z]\.)+[a-z]", w):
                    continue
        cuts.append(m.end())
    pieces, prev = [], 0
    for c in cuts + [len(text)]:
        piece = text[prev:c].strip()
        if piece:
            pieces.append(piece)
        prev = c
    return [s for s in pieces if re.search(r"[A-Za-z]", re.sub(r"\\[A-Za-z]+", "", s))]


# ---------------------------------------------------------------- tree


class Tree:
    """Nodes are [kind, content, parent_index]; node 0 is the document root."""

    def __init__(self, root_content):
        self.nodes = [["document", root_content, None]]
        self.headings = [(0, 0)]  # (level, node index)
        self.lists = []  # [list index, current item index or None]
        self.buffer = []
        self.item_text = {}

    def add(self, kind, content, parent):
        self.nodes.append([kind, content, parent])
        return len(self.nodes) - 1

    def container(self):
        if self.lists:
            lst, item = self.lists[-1]
            return item if item is not None else lst
        return self.headings[-1][1]

    def flush(self):
        text = normalize_space(" ".join(self.buffer))
        self.buffer = []
        if not text:
            return
        parent = self.container()
        if self.lists and self.lists[-1][1] is not None:
            self.item_text.setdefault(parent, []).append(text)
        for sentence in split_sentences(text):
            self.add("sentence", sentence, parent)

    def heading(self, level, title):
        self.flush()
        self.close_lists()
        while self.headings[-1][0] >= level:
            self.headings.pop()
        node = self.add("heading", title, self.headings[-1][1])
        self.headings.append((level, node))

    def to_top(self):
        self.flush()
        self.close_lists()
        self.headings = self.headings[:1]

    def close_lists(self):
        while self.lists:
            self.end_list()

    def begin_list(self):
        self.flush()
        self.lists.append([self.add("list", "", self.container()), None])

    def item(self, label):
        self.flush()
        if not self.lists:
            self.begin_list()
        node = self.add("item", "", self.lists[-1][0])
        self.lists[-1][1] = node
        if label:
            self.buffer.append(label)

    def end_list(self):
        self.flush()
        lst, _ = self.lists.pop()
        # Component contents: their own text, so identical items / lists deduplicate
        items = [i for i, n in enumerate(self.nodes) if n[2] == lst and n[0] == "item"]
        for i in items:
            self.nodes[i][1] = " ".join(self.item_text.pop(i, []))
        self.nodes[lst][1] = " | ".join(self.nodes[i][1] for i in items)

    def leaf(self, kind, content):
        self.flush()
        self.add(kind, content, self.container())


def _levels(body):
    used = {m.group(1) for m in _TOKEN.finditer(body) if m.group(1)}
    ranked = [s for s in SECTIONING if s in used]
    return {name: i + 1 for i, name in enumerate(ranked)}


def build(body, root_content):
    """Build the hierarchy of one cleaned, math-normalized document body."""
    tree = Tree(root_content)
    levels = _levels(body)
    skip_level = None  # inside a "References" section
    i = 0
    for m in _TOKEN.finditer(body):
        if m.start() < i:
            continue
        if skip_level is None:
            tree.buffer.append(body[i : m.start()])
        i = m.end()
        section, env_begin, env_end = m.group(1), m.group(3), m.group(4)

        if section:
            if body[i : i + 1] == "[":
                close = body.find("]", i)
                i = close + 1 if close != -1 else i
            title, i = read_group(body, i)
            title = normalize_space(title or "")
            level = levels[section]
            if skip_level is not None and level > skip_level:
                continue
            skip_level = None
            if _REFERENCE_TITLES.match(title):
                tree.flush()
                skip_level = level
                continue
            tree.heading(level, title)
        elif skip_level is not None:
            continue
        elif env_begin:
            name = env_begin.strip()
            if name in LISTS:
                tree.begin_list()
            elif name in HEADING_ENVS:
                tree.to_top()
                tree.heading(1, HEADING_ENVS[name])
            elif name in FLOATS or name in SKIP_ENVS or name == "equation":
                _, end = find_env_end(body, name, i)
                if name in FLOATS:
                    content = re.sub(r"\s+", " ", body[m.start() : end]).strip()
                    tree.leaf("figure", content)
                elif name == "equation":
                    tree.leaf("formula", re.sub(r"\s+", " ", body[m.start() : end]).strip())
                i = end
        elif env_end:
            name = env_end.strip()
            if name in LISTS and tree.lists:
                tree.end_list()
            elif name in HEADING_ENVS:
                tree.to_top()
        elif m.group(5):  # \item[label]
            label = None
            if body[i : i + 1] == "[":
                close = body.find("]", i)
                if close != -1:
                    label, i = body[i + 1 : close], close + 1
            tree.item(label)
        elif m.group(6):  # aastex \acknowledgments
            tree.to_top()
            tree.heading(1, "Acknowledgments")
    if skip_level is None:
        tree.buffer.append(body[i:])
    tree.flush()
    tree.close_lists()
    return tree.nodes
