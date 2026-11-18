"""Window generation and chunk caching."""

from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path


def window_ranges(
    start: str | date,
    end: str | date,
    years: int,
) -> Iterator[tuple[str, str]]:
    """Yield inclusive date windows of at most ``years`` years."""
    first = date.fromisoformat(str(start)) if not isinstance(start, date) else start
    last = date.fromisoformat(str(end)) if not isinstance(end, date) else end
    while first <= last:
        try:
            window_end = date(first.year + years, first.month, first.day) - timedelta(days=1)
        except ValueError:
            window_end = date(first.year + years, first.month, 28)
        window_end = min(window_end, last)
        yield first.isoformat(), window_end.isoformat()
        first = window_end + timedelta(days=1)


def chunk_path(source: str, start: str, end: str, base: Path) -> Path:
    """Return the cache path for a source and date window."""
    return base / source / f"{start}_{end}.csv"


def is_chunk_stale(path: Path, end: str, reference: date | None = None) -> bool:
    """Recent chunks are stale so API revisions are picked up."""
    if not path.exists():
        return True
    today = reference or date.today()
    window_end = date.fromisoformat(end)
    return window_end >= today - timedelta(days=400)
