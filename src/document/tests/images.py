"""Files built in memory for the tests: Pillow writes PNG, JPEG and PDF."""

import io

from PIL import Image


def image_bytes(size=(1000, 500), mode="RGB", format="PNG", color=1, **save_kwargs):
    output = io.BytesIO()
    Image.new(mode, size, color=color).save(output, format=format, **save_kwargs)
    return output.getvalue()


def jpeg_rotated_bytes(size=(400, 200)):
    """A JPEG stored landscape, with the EXIF orientation 6 a phone writes for
    a portrait photo: rotate 90° clockwise to display it."""
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation
    return image_bytes(size=size, format="JPEG", exif=exif)


def pdf_bytes(size=(600, 800)):
    """A one-page PDF, portrait."""
    return image_bytes(size=size, format="PDF")
