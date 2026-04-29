from __future__ import annotations

import re

_SIZE_RE = re.compile(
    r"^\s*(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>[KMGT]i?B?|B)?\s*$",
    re.IGNORECASE,
)

_DECIMAL = {
    "": 1,
    "B": 1,
    "KB": 1_000,
    "MB": 1_000_000,
    "GB": 1_000_000_000,
    "TB": 1_000_000_000_000,
}
_BINARY = {"KIB": 1024, "MIB": 1024**2, "GIB": 1024**3, "TIB": 1024**4}


class SizeParseError(ValueError):
    pass


def parse_size(text: str) -> int:
    """Parse a human-readable size into an integer number of bytes.

    Decimal units (KB/MB/GB) use 1000-based multipliers — the strict
    interpretation that matches most upload-form size limits.
    Binary units (KiB/MiB/GiB) use 1024-based multipliers.
    """
    match = _SIZE_RE.match(text)
    if not match:
        raise SizeParseError(f"Could not parse size: {text!r}")

    num = float(match.group("num"))
    unit = (match.group("unit") or "").upper()

    if unit in _BINARY:
        multiplier = _BINARY[unit]
    elif unit in _DECIMAL:
        multiplier = _DECIMAL[unit]
    elif unit in {"K", "M", "G", "T"}:
        multiplier = _DECIMAL[unit + "B"]
    else:
        raise SizeParseError(f"Unknown size unit: {unit!r}")

    result = int(num * multiplier)
    if result <= 0:
        raise SizeParseError(f"Size must be positive: {text!r}")
    return result


def format_size(num_bytes: int) -> str:
    """Render a byte count as a human-readable string using decimal units."""
    if num_bytes < 1_000:
        return f"{num_bytes} B"
    for unit, threshold in (("KB", 1_000_000), ("MB", 1_000_000_000), ("GB", 1_000_000_000_000)):
        if num_bytes < threshold:
            return f"{num_bytes / (threshold // 1_000):.2f} {unit}"
    return f"{num_bytes / 1_000_000_000_000:.2f} TB"
