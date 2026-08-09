# compresso

Convert files between formats and fit them under a target size.

Point it at an image or PDF, name a target format, and optionally give it a size
cap. For lossy targets it searches for the highest JPEG quality that still lands
under the cap, rather than making you guess at a quality number.

Reads HEIF/HEIC out of the box (via `pillow-heif`), which is the main reason this
exists — turning phone photos into something you can actually attach to an email
or upload to a form with a size limit.

## Install

```bash
uv tool install --python /opt/homebrew/bin/python3.12 .
```

The `--python` pin matters: some pyenv builds ship a broken `_blake2` module and
spray `unsupported hash type blake2b` tracebacks over every run. Any interpreter
with a working `hashlib` will do.

For local development instead:

```bash
uv sync
uv run compresso --help
```

## Usage

```
compresso SOURCE --to FORMAT [OPTIONS]
```

```bash
compresso photo.heic --to jpg              # → photo.jpg, beside the source
compresso photo.heic --to pdf              # → photo.pdf
compresso scan.pdf   --to png -o scan.png  # rasterize a PDF
compresso photo.png  --to jpg --max 500KB --force
```

### Options

| Flag | Description |
| --- | --- |
| `-t, --to` | Output format. One of `jpg`, `jpeg`, `png`, `gif`, `pdf`. **Required.** |
| `-m, --max` | Maximum output size — `3MB`, `500KB`, or raw bytes. Omit for no cap. |
| `-o, --output` | Output path. Defaults to `<source-stem>.<format>` next to the source. |
| `-f, --force` | Overwrite the output file if it already exists. |
| `-y, --yes` | Auto-approve downscaling for lossless targets; skips the prompt. |
| `-V, --version` | Print the version. |
| `-h, --help` | Show help. |

## How `--max` works

**Lossy targets (`jpg`, `jpeg`, `pdf`)** — binary-searches JPEG quality for the
largest file that still fits under the cap, showing each attempt as it goes. The
quality it settled on is reported when it finishes. If even the lowest quality
overshoots, it downscales.

**Lossless targets (`png`, `gif`)** — there's no quality knob to turn, so the only
way to shrink further is to drop resolution. If lossless output exceeds the cap,
you get a prompt before that happens:

```
Lossless PNG is 4.2 MB — over the 2 MB cap. Lossless formats can't shrink
further without dropping resolution.
Downscale to fit? [Y/n]
```

Pass `-y` to answer yes up front, which is what you want in a script. Declining
exits non-zero without writing anything.

Without `--max`, output is written at high quality with no size search.

## Output

On success it prints the output path and size, the source size, and — where
relevant — the JPEG quality chosen, the scale factor if it downscaled, and the
page count for multi-page PDFs. With a cap set, it also reports how much room it
left under the limit.

## Notes

- One file per invocation; there's no glob or batch mode. For a directory:
  ```bash
  for f in *.heic; do compresso "$f" --to jpg; done
  ```
- `--to pdf` produces a one-image-per-file PDF. Merging several images into one
  multi-page PDF is out of scope — `img2pdf *.jpg -o out.pdf` covers that.
- Exit codes: `0` success, `1` couldn't fit the cap / output exists without
  `--force` / user declined downscaling, `2` unparseable `--max`.

## Development

```bash
uv run pytest
uv run ruff check .
uv run mypy src
```
