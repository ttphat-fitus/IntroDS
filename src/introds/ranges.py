from dataclasses import dataclass

# (member, start_month, start_id, end_month, end_id)
ASSIGNMENTS = [
    ("m1", "2026-10", 2471, "2026-10", 7470),
    ("m2", "2026-08", 29007, "2026-09", 2833),
    ("m3", "2026-07", 18694, "2026-07", 23693),
    ("m4", "2026-07", 8694, "2026-07", 13693),
    ("m5", "2026-01", 8156, "2026-01", 13155),
]


@dataclass(frozen=True)
class Span:
    member: str
    yymm: str
    first: int
    last: int | None  # None = until the end of the month, resolved during discovery


def _yymm(month):
    year, mon = month.split("-")
    return f"{year[2:]}{mon}"


def spans(member=None):
    """Return the ID spans. A range crossing two months is split into two spans."""
    result = []
    for name, start_month, start_id, end_month, end_id in ASSIGNMENTS:
        if member and name != member:
            continue
        if start_month == end_month:
            result.append(Span(name, _yymm(start_month), start_id, end_id))
        else:
            result.append(Span(name, _yymm(start_month), start_id, None))
            result.append(Span(name, _yymm(end_month), 1, end_id))
    return result


def arxiv_id(yymm, number):
    return f"{yymm}.{number:05d}"


def folder_name(arxiv_id_):
    """2310.12345 -> 2310-12345 (folder convention suggested by the spec)."""
    return arxiv_id_.replace(".", "-").replace("/", "_")
