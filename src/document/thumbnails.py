"""Thumbnails of the documents: bytes in, a WebP image out, or nothing.

Pure -- no ORM, no storage -- so a format is tested on its own, and supporting
one more (a video, an office file) is one entry in `GENERATORS`. The service
decides when a thumbnail is made; this module decides what it looks like.

A thumbnail is a bonus, never a reason to refuse an upload: whatever goes wrong
-- an encrypted or corrupted PDF, a truncated image, a decompression bomb --
`make_thumbnail` logs it and returns None, and the front falls back to an icon
chosen from the mimetype.
"""

import io
import logging
import os
import typing as t
import warnings

import pypdfium2
from django.core.files.base import ContentFile
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

# On the longest side, in pixels.
THUMBNAIL_SIZE = 256
THUMBNAIL_FORMAT = "WEBP"


def _image_thumbnail(image: Image.Image) -> bytes:
    """The common end of every generator: orient, shrink, encode."""
    # The orientation a phone writes in the EXIF, rather than in the pixels.
    image = ImageOps.exif_transpose(image)
    if image.mode not in ("RGB", "RGBA"):
        # Palette, CMYK, 16-bit greyscale...: what WebP cannot take. RGBA only
        # when there is a transparency to keep.
        has_alpha = image.mode in ("LA", "PA") or "transparency" in image.info
        image = image.convert("RGBA" if has_alpha else "RGB")
    image.thumbnail((THUMBNAIL_SIZE, THUMBNAIL_SIZE))
    output = io.BytesIO()
    image.save(output, format=THUMBNAIL_FORMAT)
    return output.getvalue()


def thumbnail_from_image(bin_data: bytes) -> bytes:
    with warnings.catch_warnings():
        # Pillow only *warns* between `MAX_IMAGE_PIXELS` and twice that, and
        # raises above. Both are a bomb here: a thumbnail is worth no such
        # decoding.
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(bin_data)) as image:
            # A JPEG decoded at a fraction of its size when that is enough: a
            # 24 Mpx photo need not be decoded whole for 256 px.
            image.draft("RGB", (THUMBNAIL_SIZE, THUMBNAIL_SIZE))
            return _image_thumbnail(image)


def thumbnail_from_pdf(bin_data: bytes) -> bytes:
    pdf = pypdfium2.PdfDocument(bin_data)
    try:
        page = pdf[0]
        try:
            # Rendered at the scale that gives the thumbnail its size, not at a
            # fixed dpi: an A0 page would otherwise make a huge bitmap first.
            scale = THUMBNAIL_SIZE / max(page.get_size())
            image = page.render(scale=scale).to_pil()
        finally:
            page.close()
    finally:
        pdf.close()
    return _image_thumbnail(image)


# By mimetype prefix, the most specific first.
GENERATORS: t.Dict[str, t.Callable[[bytes], bytes]] = {
    "application/pdf": thumbnail_from_pdf,
    "image/": thumbnail_from_image,
}


def make_thumbnail(bin_data: bytes, mimetype: t.Optional[str], name: str = "thumbnail") -> t.Optional[ContentFile]:
    """A WebP thumbnail of `bin_data`, named after `name`, or None when the
    mimetype has no generator or when the generation fails."""
    if not mimetype:
        return None
    generator = next(
        (generator for prefix, generator in GENERATORS.items() if mimetype.startswith(prefix)),
        None,
    )
    if generator is None:
        return None
    try:
        thumbnail = generator(bin_data)
    except Exception:  # pylint: disable=broad-except
        # Deliberately broad: Pillow and pdfium raise a zoo of errors on a bad
        # file (`OSError`, `PdfiumError`, `DecompressionBombError`,
        # `ValueError`...), and none of them may refuse the upload.
        logger.warning("No thumbnail for %r (%s).", name, mimetype, exc_info=True)
        return None
    stem = os.path.splitext(os.path.basename(name))[0] or "thumbnail"
    return ContentFile(thumbnail, name=f"{stem}.webp")
