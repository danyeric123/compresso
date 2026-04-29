from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import img2pdf
import pillow_heif
import pypdfium2 as pdfium
from PIL import Image, ImageOps

pillow_heif.register_heif_opener()


PDF_SUFFIXES = {".pdf"}
LOSSY_FORMATS = {"jpg", "jpeg"}
LOSSLESS_FORMATS = {"png", "gif"}
ALL_FORMATS = LOSSY_FORMATS | LOSSLESS_FORMATS | {"pdf"}

QUALITY_MAX = 95
QUALITY_MIN = 20
DOWNSCALE_STEPS = (0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2)
PDF_RENDER_SCALE = 2.0


class CannotFitError(RuntimeError):
    """Raised when no encoding strategy gets the file under the size cap."""


class LosslessTooBigError(CannotFitError):
    """The lossless format can't fit at the source resolution; downscaling required."""

    def __init__(self, attempted_size: int, cap: int) -> None:
        super().__init__(
            f"Lossless output is {attempted_size} bytes; cannot fit under {cap} bytes "
            "without downscaling."
        )
        self.attempted_size = attempted_size
        self.cap = cap


@dataclass(frozen=True)
class FitResult:
    output_path: Path
    final_bytes: int
    quality: int | None
    scale: float
    pages: int


def normalize_format(fmt: str) -> str:
    fmt = fmt.lower().lstrip(".")
    return "jpg" if fmt == "jpeg" else fmt


def load_input(path: Path) -> list[Image.Image]:
    """Load any supported input as a list of Pillow images (one per page for PDFs)."""
    if path.suffix.lower() in PDF_SUFFIXES:
        pdf = pdfium.PdfDocument(str(path))
        try:
            return [page.render(scale=PDF_RENDER_SCALE).to_pil() for page in pdf]
        finally:
            pdf.close()

    image = Image.open(path)
    image.load()
    transposed = ImageOps.exif_transpose(image)
    return [transposed if transposed is not None else image]


def _exif_bytes(image: Image.Image) -> bytes | None:
    raw = image.info.get("exif")
    if isinstance(raw, bytes) and raw:
        return raw
    exif = image.getexif()
    if exif:
        return exif.tobytes()
    return None


def _encode_jpeg(image: Image.Image, quality: int, exif: bytes | None) -> bytes:
    rgb = image if image.mode == "RGB" else image.convert("RGB")
    buf = io.BytesIO()
    if exif is not None:
        rgb.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True, exif=exif)
    else:
        rgb.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
    return buf.getvalue()


def _encode_lossless(image: Image.Image, fmt: str) -> bytes:
    buf = io.BytesIO()
    pil_format = "PNG" if fmt == "png" else "GIF"
    exif = _exif_bytes(image) if pil_format == "PNG" else None
    if exif is not None:
        image.save(buf, format=pil_format, optimize=True, exif=exif)
    else:
        image.save(buf, format=pil_format, optimize=True)
    return buf.getvalue()


def _scale(image: Image.Image, factor: float) -> Image.Image:
    if factor >= 1.0:
        return image
    new_w = max(1, int(image.width * factor))
    new_h = max(1, int(image.height * factor))
    return image.resize((new_w, new_h), Image.Resampling.LANCZOS)


def _binary_search_quality(
    image: Image.Image,
    cap: int,
    exif: bytes | None,
    on_attempt: object = None,
) -> tuple[int, bytes] | None:
    """Find the highest JPEG quality (in [QUALITY_MIN, QUALITY_MAX]) whose output fits."""
    top = _encode_jpeg(image, QUALITY_MAX, exif)
    if callable(on_attempt):
        on_attempt(QUALITY_MAX, len(top))
    if len(top) <= cap:
        return QUALITY_MAX, top

    lo, hi = QUALITY_MIN, QUALITY_MAX - 1
    best: tuple[int, bytes] | None = None
    while lo <= hi:
        mid = (lo + hi) // 2
        data = _encode_jpeg(image, mid, exif)
        if callable(on_attempt):
            on_attempt(mid, len(data))
        if len(data) <= cap:
            best = (mid, data)
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _fit_jpeg(
    image: Image.Image,
    cap: int,
    on_attempt: object = None,
) -> tuple[bytes, int, float]:
    exif = _exif_bytes(image)
    for scale in (1.0, *DOWNSCALE_STEPS):
        scaled = _scale(image, scale)
        result = _binary_search_quality(scaled, cap, exif, on_attempt=on_attempt)
        if result is not None:
            quality, data = result
            return data, quality, scale
    raise CannotFitError(f"Could not fit JPEG under {cap} bytes even after downscaling to 20%.")


def _fit_lossless(
    image: Image.Image,
    fmt: str,
    cap: int,
    allow_downscale: bool,
) -> tuple[bytes, float]:
    data = _encode_lossless(image, fmt)
    if len(data) <= cap:
        return data, 1.0
    if not allow_downscale:
        raise LosslessTooBigError(len(data), cap)
    for scale in DOWNSCALE_STEPS:
        scaled = _scale(image, scale)
        data = _encode_lossless(scaled, fmt)
        if len(data) <= cap:
            return data, scale
    raise CannotFitError(
        f"Could not fit {fmt.upper()} under {cap} bytes even after downscaling to 20%."
    )


def _wrap_pdf(jpeg_pages: list[bytes]) -> bytes:
    result: bytes = img2pdf.convert(jpeg_pages)
    return result


def _fit_pdf(
    pages: list[Image.Image],
    cap: int,
    on_attempt: object = None,
) -> tuple[bytes, int, float]:
    """Encode each page as JPEG and wrap with img2pdf, fitting the wrapped total under cap."""
    pdf_overhead = 4_096
    per_page_cap_initial = max(1, (cap - pdf_overhead) // len(pages))

    for scale in (1.0, *DOWNSCALE_STEPS):
        for quality in (QUALITY_MAX, 85, 75, 65, 55, 45, 35, QUALITY_MIN):
            jpeg_pages: list[bytes] = []
            for page in pages:
                scaled = _scale(page, scale)
                exif = _exif_bytes(page)
                jpeg_pages.append(_encode_jpeg(scaled, quality, exif))
            wrapped = _wrap_pdf(jpeg_pages)
            if callable(on_attempt):
                on_attempt(quality, len(wrapped))
            if len(wrapped) <= cap:
                return wrapped, quality, scale
            if sum(len(p) for p in jpeg_pages) <= per_page_cap_initial * len(pages):
                # Even compressing pages further at this scale won't help; downscale.
                break
    raise CannotFitError(f"Could not fit PDF under {cap} bytes even after downscaling to 20%.")


def convert(
    source: Path,
    target_format: str,
    output: Path,
    max_size: int | None,
    *,
    overwrite: bool = False,
    allow_downscale_lossless: bool = False,
    on_attempt: object = None,
) -> FitResult:
    """Convert *source* to *target_format* and (optionally) under *max_size* bytes."""
    fmt = normalize_format(target_format)
    if fmt not in ALL_FORMATS:
        raise ValueError(f"Unsupported target format: {target_format!r}")

    if output.exists() and not overwrite:
        raise FileExistsError(f"{output} already exists. Pass overwrite=True to replace.")

    pages = load_input(source)

    if fmt == "pdf":
        if max_size is None:
            jpeg_pages = [_encode_jpeg(p, QUALITY_MAX, _exif_bytes(p)) for p in pages]
            data = _wrap_pdf(jpeg_pages)
            quality: int | None = QUALITY_MAX
            scale = 1.0
        else:
            data, quality, scale = _fit_pdf(pages, max_size, on_attempt=on_attempt)
        output.write_bytes(data)
        return FitResult(output, len(data), quality, scale, len(pages))

    image = pages[0]
    if fmt in LOSSY_FORMATS:
        if max_size is None:
            data = _encode_jpeg(image, QUALITY_MAX, _exif_bytes(image))
            quality, scale = QUALITY_MAX, 1.0
        else:
            data, quality, scale = _fit_jpeg(image, max_size, on_attempt=on_attempt)
        output.write_bytes(data)
        return FitResult(output, len(data), quality, scale, 1)

    # Lossless: PNG or GIF
    if max_size is None:
        data = _encode_lossless(image, fmt)
        scale = 1.0
    else:
        data, scale = _fit_lossless(image, fmt, max_size, allow_downscale_lossless)
    output.write_bytes(data)
    return FitResult(output, len(data), None, scale, 1)
