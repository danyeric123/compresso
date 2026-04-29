from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner
from PIL import Image

from compresso.cli import cli


def _make_png(path: Path, size: tuple[int, int] = (800, 600)) -> None:
    img = Image.new("RGB", size, color=(120, 200, 240))
    for x in range(0, size[0], 4):
        for y in range(0, size[1], 4):
            img.putpixel((x, y), ((x * 3) % 255, (y * 5) % 255, ((x + y) * 7) % 255))
    img.save(path, format="PNG")


def test_version_flag() -> None:
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "compresso" in result.output


def test_help_flag() -> None:
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "SOURCE" in result.output


def test_invalid_size_string_exits_2(tmp_path: Path) -> None:
    src = tmp_path / "x.png"
    _make_png(src)
    result = CliRunner().invoke(cli, [str(src), "--to", "jpg", "--max", "garbage"])
    assert result.exit_code == 2


def test_png_to_jpg_under_cap(tmp_path: Path) -> None:
    src = tmp_path / "in.png"
    _make_png(src)
    result = CliRunner().invoke(cli, [str(src), "--to", "jpg", "--max", "200KB"])
    assert result.exit_code == 0, result.output
    out = src.with_suffix(".jpg")
    assert out.exists()
    assert out.stat().st_size <= 200_000


def test_refuses_overwrite_without_force(tmp_path: Path) -> None:
    src = tmp_path / "in.png"
    _make_png(src)
    out = src.with_suffix(".jpg")
    out.write_bytes(b"existing")
    result = CliRunner().invoke(cli, [str(src), "--to", "jpg"])
    assert result.exit_code == 1
    assert out.read_bytes() == b"existing"


def test_force_overwrites(tmp_path: Path) -> None:
    src = tmp_path / "in.png"
    _make_png(src)
    out = src.with_suffix(".jpg")
    out.write_bytes(b"existing")
    result = CliRunner().invoke(cli, [str(src), "--to", "jpg", "--force"])
    assert result.exit_code == 0, result.output
    assert out.read_bytes() != b"existing"
