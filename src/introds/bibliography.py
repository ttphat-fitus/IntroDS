"""Bibliography extraction for Milestone 2.

Sources, in the order they are tried for a version:
- `.bib` files named by \\bibliography{...} / \\addbibresource{...} (only cited entries are kept,
  like BibTeX does, unless \\nocite{*});
- \\bibitem entries of a `thebibliography` environment in the TeX or in a `.bbl` file
  (natbib / plain BibTeX output), converted to BibTeX fields with regular expressions;
- biblatex `.bbl` files (\\entry ... \\endentry).

Every entry becomes {key, entry_type, title, authors, year, doi, journal, url, source}.
"""

import re

from .latex import read_group

_CITE = re.compile(r"\\[A-Za-z]*cite[A-Za-z]*\*?\s*(?:\[[^\]]*\]\s*){0,2}\{([^}]*)\}")
_BIB_COMMAND = re.compile(
    r"\\(?:bibliography|addbibresource|nobibliography)\s*(?:\[[^\]]*\])?\{([^}]*)\}"
)
_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s,;{}\\\"']+[^\s,;{}\\\"'.])")
_ARXIV = re.compile(
    r"(?:arxiv[:\s/]*|abs/)(\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})", re.IGNORECASE
)
_YEAR = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")
_URL = re.compile(r"\\(?:url|href)\s*\{([^}]*)\}")


# ---------------------------------------------------------------- text helpers


def clean_value(value):
    """Strip LaTeX markup from a field value: accents, braces, formatting commands."""
    if not value:
        return None
    v = re.sub(
        r"\\(?:[`'^\"~=.]|[uvHtcdbk](?![A-Za-z]))\s*\{?\\?([A-Za-z])\}?", r"\1", value
    )  # accents
    v = re.sub(r"\\\\(\[[^\]]*\])?|\\ ", " ", v)  # forced line breaks and control spaces
    v = v.replace("\\&", "&").replace("\\%", "%").replace("\\_", "_").replace("\\$", "$")
    v = re.sub(
        r"\\(?:emph|textbf|textit|textsc|textrm|textsf|texttt|mbox|url|href|bf|it|em|sc)\b\s*",
        "",
        v,
    )
    v = re.sub(r"\\[A-Za-z]+\s*", " ", v)
    v = v.replace("{", "").replace("}", "").replace("~", " ")
    v = re.sub(r"\s+", " ", v).strip(" ,.;:")
    return v or None


def cited_keys(text):
    """Citation keys used by \\cite-like commands (and \\nocite); '*' means every entry."""
    keys = set()
    for m in _CITE.finditer(text):
        keys.update(k.strip() for k in m.group(1).split(",") if k.strip())
    return keys


def bib_resources(text):
    """File names given to \\bibliography{a,b} / \\addbibresource{a.bib}."""
    names = []
    for m in _BIB_COMMAND.finditer(text):
        for name in m.group(1).split(","):
            name = name.strip()
            if name:
                names.append(name if name.endswith(".bib") else f"{name}.bib")
    return names


def split_authors(value):
    if not value:
        return []
    parts = re.split(r"\s+and\s+", value.strip(), flags=re.IGNORECASE)
    authors = []
    for p in parts:
        p = clean_value(p)
        if not p or p.lower() in {"others", "et al", "et al."}:
            continue
        if "," in p:  # "Last, First"
            last, _, first = p.partition(",")
            p = f"{first.strip()} {last.strip()}".strip()
        authors.append(p)
    return authors


def _entry(key, entry_type, title, authors, year, doi, journal, url, source):
    year_match = _YEAR.search(year or "") if year else None
    return {
        "key": key,
        "entry_type": (entry_type or "misc").lower(),
        "title": clean_value(re.sub(r"https?://\S+\s*", "", title)) if title else None,
        "authors": authors,
        "year": int(year_match.group(1)) if year_match else None,
        "doi": doi,
        "journal": clean_value(journal),
        "url": url,
        "source": source,
    }


# ---------------------------------------------------------------- .bib


def _bib_value(body, i):
    """Parse one field value starting at i: {...}, "...", a number or a macro, with # concatenation."""
    parts, n = [], len(body)
    while i < n:
        while i < n and body[i] in " \t\n":
            i += 1
        if i >= n:
            break
        c = body[i]
        if c == "{":
            v, i = read_group(body, i)
            parts.append(v or "")
        elif c == '"':
            j, depth = i + 1, 0
            while j < n and not (body[j] == '"' and depth == 0 and body[j - 1] != "\\"):
                depth += {"{": 1, "}": -1}.get(body[j], 0)
                j += 1
            parts.append(body[i + 1 : j])
            i = j + 1
        else:
            m = re.match(r"[A-Za-z0-9_.:\-]+", body[i:])
            if not m:
                break
            parts.append(m.group(0))
            i += m.end()
        while i < n and body[i] in " \t\n":
            i += 1
        if i < n and body[i] == "#":
            i += 1
            continue
        break
    return "".join(parts), i


_BIB_HEAD = re.compile(r"@\s*([A-Za-z]+)\s*\{\s*([^,\s{}]+)\s*,")


def parse_bib(text, keys=None):
    """{key: fields} for the @type{key, ...} entries of a .bib file (only `keys` when given:
    some papers ship a 40+ MB bibliography of which they cite a few dozen entries)."""
    entries = {}
    for m in _BIB_HEAD.finditer(text):
        entry_type = m.group(1).lower()
        if entry_type in {"comment", "preamble", "string"}:
            continue
        if keys is not None and m.group(2) not in keys:
            continue
        brace = text.index("{", m.start())
        body, _ = read_group(text, brace)
        if not body or "," not in body:
            continue
        key, _, rest = body.partition(",")
        fields, i = {"ENTRYTYPE": entry_type}, 0
        for fm in re.finditer(r"([A-Za-z][A-Za-z0-9_\-]*)\s*=\s*", rest):
            if fm.start() < i:
                continue
            value, i = _bib_value(rest, fm.end())
            fields[fm.group(1).lower()] = value
        entries[key.strip()] = fields
    return entries


def from_bib_fields(key, f):
    url = f.get("url") or None
    eprint = f.get("eprint") or (_ARXIV.search(f.get("journal", "") or "") or [None, None])[1]
    if not url and eprint and re.match(r"\d{4}\.\d{4,5}", eprint):
        url = f"https://arxiv.org/abs/{eprint}"
    doi = f.get("doi") or None
    if doi:
        doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi.strip())
    return _entry(
        key,
        f.get("ENTRYTYPE"),
        f.get("title"),
        split_authors(f.get("author")),
        f.get("year") or f.get("date"),
        doi,
        f.get("journal") or f.get("journaltitle") or f.get("booktitle"),
        url,
        "bib",
    )


# ---------------------------------------------------------------- \bibitem (natbib / BibTeX)

_ITEM_TITLE = re.compile(r"``(.+?)''|\"(.+?)\"|\\(?:emph|textit|it)\s*\{(.+?)\}", re.DOTALL)


def _split_bibitem_authors(text):
    text = clean_value(text) or ""
    pieces = [p.strip() for p in re.split(r",\s*(?:and\s+)?|\s+and\s+|;\s*", text) if p.strip()]
    authors = []
    for p in pieces:
        if authors and re.fullmatch(r"(?:[A-Z]\.?[-\s]*){1,4}", p):  # "Vaswani, A." style
            authors[-1] = f"{p} {authors[-1]}"
        elif p.lower() not in {"et al", "et al.", "others"}:
            authors.append(p)
    return authors


_BIBINFO = re.compile(r"\\bibinfo\s*\{(\w+)\}\s*\{((?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*)\}")


def _bibinfo_entry(key, rest, source):
    """revtex / APS style: every field is wrapped in \\bibinfo{field}{value}."""
    fields = {}
    for name, value in _BIBINFO.findall(rest):
        fields.setdefault(name.lower(), []).append(value)
    first = {name: values[0] for name, values in fields.items()}
    authors = [a for a in (clean_value(v) for v in fields.get("author", [])) if a]
    doi = _DOI.search(rest)
    arxiv = _ARXIV.search(rest)
    url = (_URL.findall(rest) or [None])[0]
    if not url and arxiv and re.match(r"\d{4}\.\d{4,5}", arxiv.group(1)):
        url = f"https://arxiv.org/abs/{arxiv.group(1)}"
    venue = first.get("journal") or first.get("booktitle") or first.get("publisher")
    if "booktitle" in first:
        entry_type = "inproceedings"
    elif "journal" in first:
        entry_type = "article"
    elif "publisher" in first:
        entry_type = "book"
    else:
        entry_type = "misc"
    return _entry(
        key,
        entry_type,
        first.get("title"),
        authors,
        first.get("year") or (_YEAR.findall(rest) or [None])[-1],
        doi.group(1) if doi else None,
        venue,
        url,
        source,
    )


def _bibitem_entry(key, rest, source):
    rest = rest.strip()
    if "\\bibinfo" in rest:
        return _bibinfo_entry(key, rest, source)
    urls = _URL.findall(rest)
    doi = _DOI.search(rest)
    arxiv = _ARXIV.search(rest)
    years = _YEAR.findall(rest)
    blocks = [b.strip() for b in re.split(r"\\newblock", rest) if b.strip()]
    if len(blocks) >= 2:
        authors, title, venue = blocks[0], blocks[1], " ".join(blocks[2:])
    else:
        m = _ITEM_TITLE.search(rest)
        if m:
            title = next(g for g in m.groups() if g)
            authors, venue = rest[: m.start()], rest[m.end() :]
        else:  # "Authors. Title. Venue, year."
            parts = re.split(r"(?<=[a-z\)\]}])\.\s+(?=[A-Z])", rest, maxsplit=2)
            authors = parts[0]
            title = parts[1] if len(parts) > 1 else None
            venue = parts[2] if len(parts) > 2 else ""
    venue_clean = clean_value(re.sub(r"^\s*In\s+", "", venue)) or ""
    if re.search(r"\bIn\b|Proc\.|Proceedings|Conference|Workshop|Symposium", venue):
        entry_type = "inproceedings"
    elif re.search(r"Press|Publishers?|Springer[- ]Verlag", venue) and not re.search(
        r"\d+\s*\(\d+\)", venue
    ):
        entry_type = "book"
    elif re.search(r"\d+\s*\(\d+\)|\bvol\b|\bVol\b|J\.|Journal|Letters|Review|Trans\.", venue):
        entry_type = "article"
    else:
        entry_type = "misc"
    url = urls[0] if urls else None
    if not url and arxiv and re.match(r"\d{4}\.\d{4,5}", arxiv.group(1)):
        url = f"https://arxiv.org/abs/{arxiv.group(1)}"
    return _entry(
        key,
        entry_type,
        title,
        _split_bibitem_authors(authors),
        years[-1] if years else None,
        doi.group(1) if doi else None,
        venue_clean[:300] or None,
        url,
        source,
    )


def parse_bibitems(text, source):
    """Entries of every \\bibitem[label]{key} ... in text (thebibliography or a .bbl)."""
    end = text.find("\\end{thebibliography}")
    if end != -1:
        text = text[:end]
    entries = []
    chunks = re.split(r"\\bibitem\b", text)[1:]
    for chunk in chunks:
        i = 0
        while i < len(chunk) and chunk[i] in " \t\n":
            i += 1
        if chunk[i : i + 1] == "[":  # optional label, may contain braces
            depth, j = 0, i
            while j < len(chunk):
                depth += {"[": 1, "]": -1}.get(chunk[j], 0)
                if depth == 0:
                    break
                j += 1
            i = j + 1
        key, i = read_group(chunk, i)
        if not key:
            continue
        entries.append(_bibitem_entry(key.strip(), chunk[i:], source))
    return entries


# ---------------------------------------------------------------- biblatex .bbl

_BL_FIELD = re.compile(r"\\field\{([^}]+)\}\{((?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*)\}")
_BL_VERB = re.compile(r"\\verb\{([^}]+)\}\s*\\verb\s+(.+?)\s*\\endverb", re.DOTALL)
_BL_NAME = re.compile(
    r"family=\{((?:[^{}]|\{[^{}]*\})*)\}(?:(?!family=).)*?given=\{((?:[^{}]|\{[^{}]*\})*)\}",
    re.DOTALL,
)


def parse_biblatex_bbl(text):
    entries = []
    for m in re.finditer(r"\\entry\{([^}]*)\}\{([^}]*)\}(.*?)\\endentry", text, re.DOTALL):
        key, entry_type, body = m.group(1), m.group(2), m.group(3)
        fields = {f: v for f, v in _BL_FIELD.findall(body)}
        verbs = {f: v.strip() for f, v in _BL_VERB.findall(body)}
        names = body.split("\\name{author}", 1)
        author_block = names[1].split("\\list{", 1)[0] if len(names) > 1 else ""
        authors = [
            clean_value(f"{given} {family}") for family, given in _BL_NAME.findall(author_block)
        ]
        url = verbs.get("url")
        eprint = fields.get("eprint")
        if not url and eprint and re.match(r"\d{4}\.\d{4,5}", eprint):
            url = f"https://arxiv.org/abs/{eprint}"
        entries.append(
            _entry(
                key,
                entry_type,
                fields.get("title"),
                [a for a in authors if a],
                fields.get("year") or fields.get("date"),
                verbs.get("doi"),
                fields.get("journaltitle") or fields.get("booktitle") or fields.get("journal"),
                url,
                "bbl",
            )
        )
    return entries
