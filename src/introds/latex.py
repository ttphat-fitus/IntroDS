"""LaTeX source handling for Milestone 2: root detection, \\input / \\include gathering, comment
removal, cleanup of formatting commands and math normalization.

Everything is regex / scanner based (no TeX engine): it only needs to be right for the
constructs that matter for the hierarchy, and fast enough for ~30k versions.
"""

import re
from pathlib import Path

MAX_INCLUDE_DEPTH = 20

# ---------------------------------------------------------------- reading and comments

_COMMENT_ENV = re.compile(r"\\begin\{comment\}.*?\\end\{comment\}", re.DOTALL)
_IFFALSE = re.compile(r"\\iffalse\b.*?\\fi\b", re.DOTALL)


def read_text(path):
    data = Path(path).read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    return text.replace("\r\n", "\n").replace("\r", "\n")  # old Mac files use bare CR


def strip_comments(text):
    """Drop `% ...` comments (an escaped `\\%` is kept), comment environments and \\iffalse blocks.

    A commented-out \\input therefore disappears and is never followed.
    """
    out = []
    for line in text.split("\n"):
        i = line.find("%")
        while i != -1:
            backslashes = len(line[:i]) - len(line[:i].rstrip("\\"))
            if backslashes % 2 == 0:  # not escaped
                line = line[:i]
                break
            i = line.find("%", i + 1)
        out.append(line)
    text = "\n".join(out)
    text = _COMMENT_ENV.sub("", text)
    return _IFFALSE.sub("", text)


# ---------------------------------------------------------------- balanced groups


def read_group(text, i, open_="{", close="}"):
    """Return (content, end) for the group starting at the first non-space char at/after i."""
    n = len(text)
    while i < n and text[i] in " \t\n":
        i += 1
    if i >= n or text[i] != open_:
        return None, i
    depth, j = 0, i
    while j < n:
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == open_:
            depth += 1
        elif c == close:
            depth -= 1
            if depth == 0:
                return text[i + 1 : j], j + 1
        j += 1
    return text[i + 1 :], n  # unbalanced: take the rest


def find_env_end(text, name, start):
    """Index just after the \\end{name} matching a \\begin{name} that ended at `start`."""
    begin, end = f"\\begin{{{name}}}", f"\\end{{{name}}}"
    depth, i = 1, start
    while depth:
        b, e = text.find(begin, i), text.find(end, i)
        if e == -1:
            return len(text), len(text)
        if b != -1 and b < e:
            depth, i = depth + 1, b + len(begin)
        else:
            depth, i = depth - 1, e + len(end)
    return i - len(end), i


# ---------------------------------------------------------------- multi-file gathering

_DOCCLASS = re.compile(r"\\document(?:class|style)\b")
_INCLUDE = re.compile(
    r"\\(?:(input|include|subfile|InputIfFileExists)\s*\{([^}]*)\}"
    r"|(import|subimport|inputfrom|includefrom)\s*\{([^}]*)\}\s*\{([^}]*)\}"
    r"|input\s+([^\s{}\\]+))"
)


_AUXILIARY_NAME = re.compile(
    r"template|supp|appendix|response|rebuttal|reply|cover|letter|guideline|sample|example"
    r"|highlight|poster|slides|review|instructions",
    re.IGNORECASE,
)


_STANDALONE = re.compile(r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{standalone\}")


def find_root(version_dir, sources):
    """The publication root: the file whose compilation path declares \\documentclass and opens
    \\begin{document}.

    Usually one file does both. The class may also sit in an \\input preamble, or the document
    may be opened by an \\input file, so candidates are judged on their gathered text. Among
    valid roots, auxiliary names (template, supplement, response, ...) lose, then the longest
    body wins (the paper rather than a cover letter or a template left in the archive).
    """
    candidates = [
        rel
        for rel, text in sources.items()
        if _DOCCLASS.search(text) or "\\begin{document}" in text
    ]
    if not candidates:
        return max(sources, key=lambda r: len(sources[r]))
    if len(candidates) == 1:
        return candidates[0]

    def score(rel):
        full, _ = gather(sources, rel)
        valid = bool(_DOCCLASS.search(full)) and "\\begin{document}" in full
        body = len(split_document(full)[1]) if valid else 0
        standalone = bool(_STANDALONE.search(full))  # a figure compiled on its own
        return (valid, not standalone, not _AUXILIARY_NAME.search(Path(rel).stem), body, rel)

    return max(candidates, key=score)


_SIMPLE_DEF = re.compile(
    r"\\(?:newcommand|renewcommand|providecommand|def)\s*\{?\\([A-Za-z@]+)\}?\s*\{([^{}\\]*)\}"
)


def path_macros(sources):
    """Argument-free macros with a plain value, e.g. \\newcommand{\\CHAPTERSDIR}{chapters}."""
    return {
        name: value.strip()
        for text in sources.values()
        for name, value in _SIMPLE_DEF.findall(text)
    }


def _resolve(target, base_dirs, sources, macros=None):
    target = target.strip().strip('"')
    if macros and "\\" in target:  # \input{\CHAPTERSDIR/intro}
        target = re.sub(r"\\([A-Za-z@]+)", lambda m: macros.get(m.group(1), ""), target)
    for base in base_dirs:
        for name in (target, f"{target}.tex"):
            rel = str(Path(base, name)) if base else name
            rel = str(Path(rel))  # normalise ./ and duplicate slashes
            if rel in sources:
                return rel
    # Last resort: a unique file with that name anywhere in the archive
    wanted = {Path(target).name, f"{Path(target).name}.tex"}
    hits = [rel for rel in sources if Path(rel).name in wanted]
    return hits[0] if len(hits) == 1 else None


def gather(sources, root):
    """Expand \\input / \\include transitively from the root (comments already removed).

    Returns (text, used): the flattened document and the list of files on the compilation path.
    """
    used = []
    macros = path_macros(sources)

    def expand(rel, depth):
        used.append(rel)
        text = sources[rel]
        if depth >= MAX_INCLUDE_DEPTH:
            return text
        here = str(Path(rel).parent) if "/" in rel else ""

        def repl(m):
            if m.group(1):
                target, bases = m.group(2), ["", here]
            elif m.group(3):
                target, bases = m.group(5), [m.group(4).strip().rstrip("/"), here]
            else:
                target, bases = m.group(6), ["", here]
            found = _resolve(target, bases, sources, macros)
            if found is None or found in used:  # missing file or include cycle
                return " "
            sep = "\n\\clearpage\n" if m.group(1) == "include" else "\n"
            return sep + expand(found, depth + 1) + "\n"

        return _INCLUDE.sub(repl, text)

    return expand(root, 0), used


_IN_DEFINITION = re.compile(
    r"\\(?:def|e?def|g?def|newcommand|renewcommand|providecommand|let)\b[^\n]*$"
)


def split_document(text):
    """(preamble, body): body is what lies between \\begin{document} and the last \\end{document}.

    A \\begin{document} inside a macro definition (\\def\\bd{\\begin{document}}) is not the start.
    """
    starts = [m.start() for m in re.finditer(r"\\begin\{document\}", text)]
    real = [i for i in starts if not _IN_DEFINITION.search(text[max(0, i - 200) : i])]
    if not starts:
        return "", text
    b = real[0] if real else starts[-1]
    e = text.rfind("\\end{document}")
    end = e if e > b else len(text)
    return text[:b], text[b + len("\\begin{document}") : end]


def command_arg(text, name):
    """Argument of the first \\name[...]{...} in text (balanced), or None."""
    m = re.search(rf"\\{name}\*?\s*(?:\[[^\]]*\]\s*)?(?=\{{)", text)
    if not m:
        return None
    arg, _ = read_group(text, m.end())
    return arg


# ---------------------------------------------------------------- cleanup

# Formatting commands without semantic content, dropped with their arguments
_DROP_WITH_ARGS = {
    "vspace": 1,
    "hspace": 1,
    "vskip": 0,
    "hskip": 0,
    "label": 1,
    "setlength": 2,
    "addtolength": 2,
    "setcounter": 2,
    "addtocounter": 2,
    "thispagestyle": 1,
    "pagestyle": 1,
    "enlargethispage": 1,
    "linespread": 1,
    "renewcommand": 2,
    "newcommand": 2,
    "providecommand": 2,
    "captionsetup": 1,
    "graphicspath": 1,
    "bibliographystyle": 1,
    "fontsize": 2,
    "selectfont": 0,
    "color": 1,
    "definecolor": 3,
    "nocite": 1,
    "addcontentsline": 3,
    "vphantom": 1,
    "hphantom": 1,
    "phantom": 1,
    "rule": 2,
    "title": 1,
    "author": 1,
    "affiliation": 1,
    "address": 1,
    "email": 1,
    "date": 1,
    "thanks": 1,
    "keywords": 1,
    "institute": 1,
    "affil": 1,
    "orcid": 1,
    "ccsdesc": 1,
    "corresp": 1,
    "titlerunning": 1,
    "authorrunning": 1,
    "icmltitle": 1,
    "icmlauthor": 2,
    "icmlaffiliation": 2,
    "icmlcorrespondingauthor": 2,
    "icmlkeywords": 1,
    "pacs": 1,
    "IEEEauthorblockN": 1,
    "altaffiltext": 2,
    "altaffilmark": 1,
    "correspondingauthor": 1,
    "shortauthors": 1,
    "received": 1,
    "revised": 1,
    "accepted": 1,
    "published": 1,
    "submitjournal": 1,
    "slugcomment": 1,
    "journalinfo": 1,
    "IEEEauthorblockA": 1,
    "markboth": 2,
    "shorttitle": 1,
}
_DROP_BARE = [
    "centering",
    "raggedright",
    "raggedleft",
    "noindent",
    "small",
    "footnotesize",
    "scriptsize",
    "tiny",
    "large",
    "Large",
    "LARGE",
    "huge",
    "Huge",
    "normalsize",
    "toprule",
    "midrule",
    "bottomrule",
    "hline",
    "newpage",
    "clearpage",
    "cleardoublepage",
    "pagebreak",
    "linebreak",
    "nolinebreak",
    "maketitle",
    "tableofcontents",
    "listoffigures",
    "listoftables",
    "medskip",
    "smallskip",
    "bigskip",
    "vfill",
    "hfill",
    "protect",
    "FloatBarrier",
    "balance",
    "sloppy",
    "nobreak",
    "allowbreak",
    "indent",
    "onecolumn",
    "twocolumn",
    "frenchspacing",
    "normalfont",
    "bfseries",
    "itshape",
    "rmfamily",
    "sffamily",
    "ttfamily",
    "scshape",
    "upshape",
    "mdseries",
    "IEEEpeerreviewmaketitle",
    "IEEEoverridecommandlockouts",
    "printccsdesc",
    "acmConference",
    "notag",
    "nonumber",
    "displaystyle",
    "textstyle",
]
# Wrappers whose argument is kept: \textbf{x} -> x
_UNWRAP = [
    "textbf",
    "textit",
    "emph",
    "textsc",
    "textrm",
    "textsf",
    "texttt",
    "textup",
    "textmd",
    "textnormal",
    "underline",
    "mbox",
    "hbox",
    "makebox",
    "fbox",
    "uline",
    "hl",
    "sout",
    "st",
    "xout",
    "textsl",
    "ul",
]
_COLOR = re.compile(r"\\(?:textcolor|colorbox)\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}")
_MAKEAT = re.compile(r"\\makeatletter\b.*?\\makeatother\b", re.DOTALL)

_BARE_RE = re.compile(r"\\(?:" + "|".join(_DROP_BARE) + r")(?![A-Za-z])\*?\s*")
_PLACEMENT = re.compile(r"(\\begin\{(?:figure|table|algorithm|wrapfigure)\*?\})\s*\[[^\]]*\]")


def _drop_commands(text, names):
    pattern = re.compile(
        r"\\(" + "|".join(sorted(names, key=len, reverse=True)) + r")(?![A-Za-z])\*?"
    )
    out, i = [], 0
    for m in pattern.finditer(text):
        if m.start() < i:
            continue
        out.append(text[i : m.start()])
        j = m.end()
        nargs = names[m.group(1)]
        while j < len(text) and text[j] in " \t" and nargs:
            j += 1
        if j < len(text) and text[j] == "[":  # optional argument
            close = text.find("]", j)
            j = close + 1 if close != -1 else j
        for _ in range(nargs):
            arg, k = read_group(text, j)
            if arg is None:
                break
            j = k
        i = j
    out.append(text[i:])
    return "".join(out)


def _unwrap(text):
    pattern = re.compile(r"\\(?:" + "|".join(_UNWRAP) + r")(?![A-Za-z])\s*(?=\{)")
    for _ in range(3):  # nested wrappers
        out, i, changed = [], 0, False
        for m in pattern.finditer(text):
            if m.start() < i:
                continue
            arg, end = read_group(text, m.end())
            if arg is None:
                continue
            out.append(text[i : m.start()])
            out.append(arg)
            i, changed = end, True
        out.append(text[i:])
        text = "".join(out)
        if not changed:
            break
    return text


def cleanup(text):
    """Remove formatting without semantic meaning (\\centering, [htpb], \\midrule, ...)."""
    text = _MAKEAT.sub(" ", text)  # macro (re)definitions, not content
    text = _COLOR.sub("", text)  # \textcolor{red}{x} -> {x}
    text = _PLACEMENT.sub(r"\1", text)
    text = _drop_commands(text, _DROP_WITH_ARGS)
    text = _BARE_RE.sub(" ", text)
    return _unwrap(text)


# ---------------------------------------------------------------- math normalization

_BLOCK_ENVS = {
    "equation": None,
    "equation*": None,
    "displaymath": None,
    "math": "inline",
    "align": "aligned",
    "align*": "aligned",
    "eqnarray": "aligned",
    "eqnarray*": "aligned",
    "flalign": "aligned",
    "flalign*": "aligned",
    "alignat": "aligned",
    "alignat*": "aligned",
    "gather": "gathered",
    "gather*": "gathered",
    "multline": "gathered",
    "multline*": "gathered",
}
_BLOCK_RE = re.compile(r"\\begin\{(" + "|".join(re.escape(e) for e in _BLOCK_ENVS) + r")\}")
_MATH_NOISE = re.compile(r"\\(?:label\{[^}]*\}|nonumber\b|notag\b)")


def _equation(body, inner=None):
    body = _MATH_NOISE.sub("", body).strip()
    if inner:
        body = f"\\begin{{{inner}}}{body}\\end{{{inner}}}"
    return f"\\begin{{equation}}{body}\\end{{equation}}"


def normalize_math(text):
    """Block math -> \\begin{equation}...\\end{equation}; inline math -> $...$."""
    out, i = [], 0
    for m in _BLOCK_RE.finditer(text):
        if m.start() < i:
            continue
        name = m.group(1)
        end_start, end = find_env_end(text, name, m.end())
        body = text[m.end() : end_start]
        if name.startswith("alignat"):  # \begin{alignat}{2}
            _, k = read_group(body, 0)
            body = body[k:]
        out.append(text[i : m.start()])
        kind = _BLOCK_ENVS[name]
        out.append(f"${body.strip()}$" if kind == "inline" else _equation(body, kind))
        i = end
    out.append(text[i:])
    text = "".join(out)
    text = re.sub(r"\$\$(.+?)\$\$", lambda m: _equation(m.group(1)), text, flags=re.DOTALL)
    text = re.sub(r"(?<!\\)\\\[(.+?)\\\]", lambda m: _equation(m.group(1)), text, flags=re.DOTALL)
    return re.sub(
        r"(?<!\\)\\\((.+?)\\\)", lambda m: f"${m.group(1).strip()}$", text, flags=re.DOTALL
    )


def normalize_space(text):
    text = text.replace("~", " ")
    text = re.sub(r"(?<!\\)\\\\(\[[^\]]*\])?", " ", text)  # forced line breaks in prose
    return re.sub(r"\s+", " ", text).strip()
