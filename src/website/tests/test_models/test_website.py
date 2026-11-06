from django.core.exceptions import ValidationError
import shutil
import tempfile

from django.test import TestCase, override_settings

from website.models import Media, Website
from website.theme import DEFAULT_THEME_ID


class TestWebsiteModel(TestCase):

    def test_primary_key_is_a_ulid(self):
        website = Website.objects.create(name="Moulinsart", headline="Le domaine")

        self.assertEqual(len(website.pk), 26)
        self.assertTrue(website.pk.isalnum())

    def test_a_fresh_row_names_the_default_theme(self):
        website = Website.objects.create(name="Moulinsart", headline="Le domaine")

        self.assertEqual(website.theme, DEFAULT_THEME_ID)
        self.assertEqual(website.theme_options, {})

    def test_two_rows_do_not_share_one_options_dict(self):
        """The `default=dict` guard: `default={}` would be one shared object."""
        first = Website.objects.create(name="A", headline="A")
        second = Website.objects.create(name="B", headline="B")

        first.theme_options["x"] = 1

        self.assertEqual(second.theme_options, {})


class TestWebsiteQuerySet(TestCase):
    """Switching theme clears the stored options, whichever writer does it."""

    def setUp(self):
        super().setUp()
        self.website = Website.objects.create(
            name="Moulinsart",
            headline="Le domaine",
            theme_options={"color_primary": "#c0392b"},
        )

    def test_switching_theme_clears_the_options(self):
        # They are keyed by the option names of ONE `option_schema`, and nothing
        # maps them onto another theme's.
        # Any string: the queryset reacts to the *presence* of `theme` in the
        # payload and does not validate it -- that is the service's job.
        Website.objects.filter(pk=self.website.pk).update(theme="some-other-theme")

        self.website.refresh_from_db()
        self.assertEqual(self.website.theme, "some-other-theme")
        self.assertEqual(self.website.theme_options, {})

    def test_options_sent_with_the_switch_still_win(self):
        """`setdefault`, not an assignment: the caller's payload takes priority."""
        Website.objects.filter(pk=self.website.pk).update(
            theme="some-other-theme", theme_options={"color_primary": "#fff"}
        )

        self.website.refresh_from_db()
        self.assertEqual(self.website.theme_options, {"color_primary": "#fff"})

    def test_an_unrelated_update_leaves_the_options_alone(self):
        Website.objects.filter(pk=self.website.pk).update(name="La Licorne")

        self.website.refresh_from_db()
        self.assertEqual(self.website.theme_options, {"color_primary": "#c0392b"})


class TestWebsiteClean(TestCase):
    """`Website.clean()` is what covers the admin, which never reaches the queryset."""

    def build(self, **values):
        values.setdefault("name", "Moulinsart")
        values.setdefault("headline", "Le domaine")
        return Website(**values)

    def test_a_known_theme_with_valid_options_passes(self):
        self.build(theme=DEFAULT_THEME_ID, theme_options={}).clean()

    def test_an_unknown_theme_is_refused(self):
        with self.assertRaises(ValidationError) as ctx:
            self.build(theme="test-nope").clean()

        self.assertIn("theme", ctx.exception.message_dict)

    def test_options_that_do_not_match_the_schema_are_refused(self):
        # Against the default theme rather than a theme from another test
        # module: the registry is process-wide state, so depending on which
        # modules happen to be loaded would make this test order-dependent.
        # `NoOptions` sets `extra="forbid"`, so an unknown key is enough.
        with self.assertRaises(ValidationError) as ctx:
            self.build(theme=DEFAULT_THEME_ID, theme_options={"nope": 1}).clean()

        self.assertIn("theme_options", ctx.exception.message_dict)

    def test_an_image_cover_passes(self):
        cover = Media(name="fusee.png", mimetype="image/png")

        self.build(cover_media=cover).clean()

    def test_a_cover_that_is_not_an_image_is_refused(self):
        cover = Media(name="journal.pdf", mimetype="application/pdf")

        with self.assertRaises(ValidationError) as ctx:
            self.build(cover_media=cover).clean()

        self.assertIn("cover_media", ctx.exception.message_dict)


class TestWebsiteCoverMedia(TestCase):

    @classmethod
    def setUpClass(cls):
        # The media delete also deletes its file: keep it away from the real
        # filestore, as `test_api.test_media` does.
        cls._media_root = tempfile.mkdtemp()
        cls._override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)

    def test_deleting_the_cover_media_unsets_the_cover(self):
        """`SET_NULL`: the media library is never blocked by the site settings."""
        cover = Media.objects.bulk_create([
            Media(name="fusee.png", content="website/fusee.png", mimetype="image/png", checksum="a" * 40),
        ])[0]
        website = Website.objects.create(name="Moulinsart", headline="Le domaine", cover_media=cover)

        Media.objects.filter(pk=cover.pk).delete()

        website.refresh_from_db()
        self.assertIsNone(website.cover_media_id)
