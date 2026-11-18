from datetime import date
from pathlib import Path

from charles.cache import is_chunk_stale, window_ranges


def test_window_boundaries():
    windows = list(window_ranges("2020-01-01", "2021-02-01", 1))
    assert windows == [
        ("2020-01-01", "2020-12-31"),
        ("2021-01-01", "2021-02-01"),
    ]


def test_stale_chunk(tmp_path: Path):
    path = tmp_path / "chunk.csv"
    path.write_text("x", encoding="utf-8")
    assert not is_chunk_stale(path, "2023-01-01", date(2025, 1, 1))
    assert is_chunk_stale(path, "2024-10-01", date(2025, 1, 1))
