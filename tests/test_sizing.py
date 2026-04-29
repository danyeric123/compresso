from __future__ import annotations

import pytest

from compresso.sizing import SizeParseError, format_size, parse_size


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3MB", 3_000_000),
        ("3 MB", 3_000_000),
        ("3mb", 3_000_000),
        ("500KB", 500_000),
        ("500K", 500_000),
        ("1.5MB", 1_500_000),
        ("1024", 1024),
        ("1024B", 1024),
        ("1MiB", 1024 * 1024),
        ("1GiB", 1024**3),
        ("2 GB", 2_000_000_000),
    ],
)
def test_parse_size_valid(text: str, expected: int) -> None:
    assert parse_size(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "MB", "-3MB", "0", "0MB", "3 XB"])
def test_parse_size_invalid(text: str) -> None:
    with pytest.raises(SizeParseError):
        parse_size(text)


def test_format_size_round_trip_human_readable() -> None:
    assert format_size(0) == "0 B"
    assert format_size(999) == "999 B"
    assert format_size(1_000) == "1.00 KB"
    assert format_size(2_500_000) == "2.50 MB"
    assert format_size(3_000_000_000) == "3.00 GB"
