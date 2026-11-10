import io
from unittest.mock import patch

from django.test import SimpleTestCase
from parameterized import parameterized
from PIL import Image

from document.tests.images import image_bytes, jpeg_rotated_bytes, pdf_bytes
from document.thumbnails import make_thumbnail


class TestMakeThumbnail(SimpleTestCase):

    def open(self, thumbnail):
        image = Image.open(io.BytesIO(thumbnail.read()))
        self.assertEqual(image.format, "WEBP")
        return image

    # ------------------------------------------
    # Supported formats
    # ------------------------------------------

    def test_png(self):
        thumbnail = make_thumbnail(image_bytes(size=(1000, 500)), "image/png", "ring.png")
        self.assertEqual(thumbnail.name, "ring.webp")
        # The longest side brought to 256, the ratio kept.
        self.assertEqual(self.open(thumbnail).size, (256, 128))

    def test_png_with_transparency_keeps_it(self):
        # Transparent: an opaque RGBA is encoded without its alpha channel.
        thumbnail = make_thumbnail(image_bytes(mode="RGBA", color=(255, 0, 0, 0)), "image/png", "ring.png")
        self.assertEqual(self.open(thumbnail).mode, "RGBA")

    @parameterized.expand([("P",), ("CMYK",), ("L",)])
    def test_mode_webp_cannot_take_is_converted(self, mode):
        image_format = "JPEG" if mode == "CMYK" else "PNG"
        thumbnail = make_thumbnail(image_bytes(mode=mode, format=image_format), "image/png", "ring.png")
        self.assertIn(self.open(thumbnail).mode, ("RGB", "RGBA"))

    def test_jpeg_follows_its_exif_orientation(self):
        # Stored 400x200, displayed 200x400.
        thumbnail = make_thumbnail(jpeg_rotated_bytes(size=(400, 200)), "image/jpeg", "frodon.jpg")
        self.assertEqual(self.open(thumbnail).size, (128, 256))

    def test_small_image_is_not_enlarged(self):
        thumbnail = make_thumbnail(image_bytes(size=(64, 32)), "image/png", "ring.png")
        self.assertEqual(self.open(thumbnail).size, (64, 32))

    def test_pdf_first_page(self):
        # 600x800 pt: rendered at the scale giving 256 px on the longest side.
        thumbnail = make_thumbnail(pdf_bytes(size=(600, 800)), "application/pdf", "map.pdf")
        self.assertEqual(thumbnail.name, "map.webp")
        self.assertEqual(self.open(thumbnail).size[1], 256)

    # ------------------------------------------
    # No thumbnail, never an error
    # ------------------------------------------

    @parameterized.expand(
        [
            ("unknown mimetype", b"PK\x03\x04", "application/zip"),
            ("no mimetype", b"PK\x03\x04", None),
        ]
    )
    def test_no_generator(self, dummy, bin_data, mimetype):
        self.assertIsNone(make_thumbnail(bin_data, mimetype, "file"))

    @parameterized.expand(
        [
            ("corrupted pdf", b"%PDF-1.4 not really a pdf", "application/pdf"),
            ("corrupted image", b"\x89PNG not really a png", "image/png"),
            ("truncated image", image_bytes()[:100], "image/png"),
        ]
    )
    def test_generation_failure(self, dummy, bin_data, mimetype):
        # Logged, for a file the generator should have read.
        with self.assertLogs("document.thumbnails", "WARNING"):
            self.assertIsNone(make_thumbnail(bin_data, mimetype, "file"))

    def test_decompression_bomb(self):
        # Above `MAX_IMAGE_PIXELS` (but below twice it, where Pillow only warns).
        with patch.object(Image, "MAX_IMAGE_PIXELS", 1000 * 500 - 1), \
                self.assertLogs("document.thumbnails", "WARNING"):
            self.assertIsNone(make_thumbnail(image_bytes(size=(1000, 500)), "image/png", "bomb.png"))
