"""Deterministic PDF parsing with PyMuPDF (no LLM here).

Pulls the plain-text layer and the embedded raster images. The provided invoice
hides its header fields (invoice number, dates, totals) inside a page-1 image,
so we surface those images for the vision step that follows.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF


# Guardrails so we never feed huge / spurious images to the vision model.
_MIN_IMAGE_PIXELS = 64 * 64
_MAX_IMAGES = 4


@dataclass
class EmbeddedImage:
    page: int
    ext: str
    width: int
    height: int
    data: bytes = field(repr=False)

    @property
    def data_url(self) -> str:
        mime = "image/png" if self.ext == "png" else f"image/{self.ext}"
        b64 = base64.b64encode(self.data).decode("ascii")
        return f"data:{mime};base64,{b64}"


@dataclass
class PdfContent:
    text: str
    images: list[EmbeddedImage]
    page_count: int

    @property
    def has_images(self) -> bool:
        return len(self.images) > 0


def extract_pdf(path: str | Path) -> PdfContent:
    """Extract text and embedded images from ``path``.

    Raises
    ------
    FileNotFoundError
        If the PDF does not exist.
    ValueError
        If the file cannot be opened/parsed as a PDF.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"PDF attachment not found: {p}")

    try:
        doc = fitz.open(p)
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError(f"Could not open PDF {p}: {exc}") from exc

    text_parts: list[str] = []
    images: list[EmbeddedImage] = []
    seen_xrefs: set[int] = set()

    try:
        for page_index in range(doc.page_count):
            page = doc[page_index]
            text_parts.append(page.get_text("text"))

            for img in page.get_images(full=True):
                xref = img[0]
                if xref in seen_xrefs or len(images) >= _MAX_IMAGES:
                    continue
                seen_xrefs.add(xref)
                try:
                    base = doc.extract_image(xref)
                except Exception:
                    continue
                width, height = base.get("width", 0), base.get("height", 0)
                if width * height < _MIN_IMAGE_PIXELS:
                    continue
                images.append(
                    EmbeddedImage(
                        page=page_index + 1,
                        ext=base.get("ext", "png"),
                        width=width,
                        height=height,
                        data=base["image"],
                    )
                )
        page_count = doc.page_count
    finally:
        doc.close()

    full_text = "\n".join(text_parts).strip()
    if not full_text and not images:
        raise ValueError(
            f"PDF {p} yielded no text and no images; it may be empty or corrupt."
        )

    return PdfContent(text=full_text, images=images, page_count=page_count)
