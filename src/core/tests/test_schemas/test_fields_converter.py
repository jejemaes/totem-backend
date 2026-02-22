import datetime
import typing as t

from annotated_types import Ge, Gt, Le, Lt, MaxLen, MinLen
from django.core.validators import URLValidator, slug_re
from django.db import models
from django.test import TestCase
from django.utils import timezone
from parameterized import parameterized
from pydantic import AnyUrl, EmailStr, IPvAnyAddress  # , Json
from pydantic.fields import FieldInfo

from core.schemas.fields import convert_db_field


class TestSchemaFieldConverter(TestCase):

    # -------------------------------------------------------------
    # Text Fields (Char, Text, Slug, Email)
    # -------------------------------------------------------------

    @parameterized.expand(
        [
            # Char Field
            (models.CharField(), str, FieldInfo()),
            (
                models.CharField(help_text=" coucou "),
                str,
                FieldInfo(description="Coucou"),
            ),
            (
                models.CharField(verbose_name="my field", max_length=42),
                str,
                FieldInfo(title="My Field", max_length=42),
            ),
            (
                models.CharField(null=True, max_length=42),
                t.Optional[str],
                FieldInfo(max_length=42, default=None),
            ),
            # Text Field
            (models.TextField(null=False), str, FieldInfo()),
            (
                models.TextField(max_length=42),
                str,
                FieldInfo(),
            ),  # textfield has no length limit
            (
                models.TextField(null=True, blank=False),
                t.Optional[str],
                FieldInfo(default=None),
            ),
            (
                models.TextField(null=True, blank=True),
                t.Optional[str],
                FieldInfo(default=None),
            ),
            # Slug
            (
                models.SlugField(),
                str,
                FieldInfo(max_length=50, pattern=slug_re),
            ),
            (
                models.SlugField(max_length=123, blank=True),
                t.Optional[str],
                FieldInfo(max_length=123, default=None, pattern=slug_re),
            ),
        ]
    )
    def test_text_field_conversion(self, django_field, expected_type, expected_field):
        python_type, field = convert_db_field(django_field, optional=False)
        self.assertEqual(python_type, expected_type)
        self.assertPydanticFieldEqual(field, expected_field)

    @parameterized.expand(
        [
            # Email
            (
                models.EmailField(),
                EmailStr,
                FieldInfo(max_length=254),
            ),  # django forces max_length
            (
                models.EmailField(null=True),
                t.Optional[EmailStr],
                FieldInfo(max_length=254, default=None),
            ),  # django forces max_length
            (
                models.EmailField(null=True, blank=False),
                t.Optional[EmailStr],
                FieldInfo(max_length=254, default=None),
            ),
            (
                models.EmailField(null=True, blank=True),
                t.Optional[EmailStr],
                FieldInfo(max_length=254, default=None),
            ),
        ]
    )
    def test_email_field_conversion(self, django_field, expected_type, expected_field):
        python_type, field = convert_db_field(django_field, optional=False)

        expected_type_optional = False
        if hasattr(expected_type, "__origin__") and expected_type.__origin__ is t.Union:
            expected_type = (
                expected_type.__args__[0]
                if expected_type.__args__[1] is type(None)
                else expected_type.__args__[1]
            )

        python_type_optional = False
        if python_type.__origin__ is t.Union:
            python_type = (
                python_type.__args__[0]
                if python_type.__args__[1] is type(None)
                else python_type.__args__[1]
            )

        self.assertEqual(python_type_optional, expected_type_optional)
        self.assertIn(expected_type, python_type.__args__)
        self.assertPydanticFieldEqual(field, expected_field)

    # -------------------------------------------------------------
    # Number Fields (Integer, Float, Boolean)
    # -------------------------------------------------------------

    @parameterized.expand(
        [
            # Integer Field
            (
                models.IntegerField(verbose_name="my field", help_text=" coucou "),
                int,
                FieldInfo(
                    title="My Field",
                    description="Coucou",
                    le=2147483647,
                    ge=-2147483648,
                ),
            ),
            (
                models.IntegerField(null=True, blank=True),
                t.Optional[int],
                FieldInfo(
                    default=None,
                    le=2147483647,
                    ge=-2147483648,
                ),
            ),
            (
                models.IntegerField(null=True, blank=False),
                t.Optional[int],
                FieldInfo(
                    default=None,
                    le=2147483647,
                    ge=-2147483648,
                ),
            ),
            (
                models.IntegerField(null=False, blank=True, default=42),
                t.Optional[int],
                FieldInfo(
                    le=2147483647,
                    ge=-2147483648,
                    default=42,
                ),
            ),
            (
                models.IntegerField(null=False, blank=False),
                int,
                FieldInfo(
                    le=2147483647,
                    ge=-2147483648,
                ),
            ),
            # Positive Integer Field
            (
                models.PositiveIntegerField(
                    verbose_name="my field", help_text=" coucou "
                ),
                int,
                FieldInfo(
                    title="My Field",
                    description="Coucou",
                    le=2147483647,
                    ge=0,
                ),
            ),
            (
                models.PositiveIntegerField(null=True, blank=True),
                t.Optional[int],
                FieldInfo(
                    default=None,
                    le=2147483647,
                    ge=0,
                ),
            ),
            (
                models.PositiveIntegerField(null=True, blank=False),
                t.Optional[int],
                FieldInfo(
                    default=None,
                    le=2147483647,
                    ge=0,
                ),
            ),
            (
                models.PositiveIntegerField(null=False, blank=True, default=42),
                t.Optional[int],
                FieldInfo(le=2147483647, ge=0, default=42),
            ),
            (
                models.PositiveIntegerField(null=False, blank=False),
                int,
                FieldInfo(
                    le=2147483647,
                    ge=0,
                ),
            ),
            # Small and Big Integer Field
            (
                models.SmallIntegerField(verbose_name="my field", help_text=" coucou "),
                int,
                FieldInfo(
                    title="My Field",
                    description="Coucou",
                    le=32767,
                    ge=-32768,
                ),
            ),
            (
                models.BigIntegerField(verbose_name="my field", help_text=" coucou "),
                int,
                FieldInfo(
                    title="My Field",
                    description="Coucou",
                    le=9223372036854775807,
                    ge=-9223372036854775808,
                ),
            ),
        ]
    )
    def test_integer_field_conversion(self, django_field, expected_type, expected_field):
        python_type, field = convert_db_field(django_field, optional=False)
        self.assertEqual(python_type, expected_type)
        self.assertPydanticFieldEqual(field, expected_field)

    @parameterized.expand(
        [
            # Float Field
            (
                models.FloatField(verbose_name="my field", help_text=" coucou "),
                float,
                FieldInfo(
                    title="My Field",
                    description="Coucou",
                ),
            ),
            (
                models.FloatField(null=False),
                float,
                FieldInfo(),
            ),
            (
                models.FloatField(null=True),
                t.Optional[float],
                FieldInfo(default=None),
            ),
        ]
    )
    def test_float_field_conversion(
        self, django_field, expected_type, expected_field
    ):
        python_type, field = convert_db_field(django_field, optional=False)
        self.assertEqual(python_type, expected_type)
        self.assertPydanticFieldEqual(field, expected_field)

    @parameterized.expand(
        [
            (
                models.BooleanField(
                    verbose_name="my field", help_text=" coucou ", default=True
                ),
                bool,
                FieldInfo(
                    title="My Field",
                    description="Coucou",
                    default=True,
                ),
            ),
            (
                models.BooleanField(null=False, default=False),
                bool,
                FieldInfo(default=False),
            ),
            (
                models.BooleanField(null=True),
                t.Optional[bool],
                FieldInfo(default=None),
            ),
            (
                models.BooleanField(null=True, default=True),
                t.Optional[bool],
                FieldInfo(default=True),
            ),
        ]
    )
    def test_boolean_field_conversion(self, django_field, expected_type, expected_field):
        python_type, field = convert_db_field(django_field, optional=False)
        self.assertEqual(python_type, expected_type)
        self.assertPydanticFieldEqual(field, expected_field)

    # -------------------------------------------------------------
    # Various Fields (IP, Url, ...)
    # -------------------------------------------------------------

    @parameterized.expand(
        [
            (
                models.IPAddressField(
                    verbose_name="my field", help_text=" coucou ", default="127.0.0.1"
                ),
                IPvAnyAddress,
                FieldInfo(
                    title="My Field",
                    description="Coucou",
                    default="127.0.0.1",
                ),
            ),
            (
                models.IPAddressField(null=False, blank=False, default="127.0.0.1"),
                IPvAnyAddress,
                FieldInfo(default="127.0.0.1"),
            ),
            (
                models.IPAddressField(null=True, blank=True),
                t.Optional[IPvAnyAddress],
                FieldInfo(default=None),
            ),
            (
                models.IPAddressField(null=True, blank=False, default="127.0.0.1"),
                t.Optional[IPvAnyAddress],
                FieldInfo(default="127.0.0.1"),
            ),
        ]
    )
    def test_ip_field_conversion(
        self, django_field, expected_type, expected_field
    ):
        python_type, field = convert_db_field(django_field, optional=False)
        self.assertEqual(python_type, expected_type)
        self.assertPydanticFieldEqual(field, expected_field)

    @parameterized.expand(
        [
            (
                models.URLField(
                    verbose_name="my field",
                    help_text=" coucou ",
                    default="http://example.com",
                ),
                AnyUrl,
                FieldInfo(
                    title="My Field",
                    description="Coucou",
                    default="http://example.com",
                    max_length=200,
                    pattern=URLValidator.regex,
                ),
            ),
            (
                models.URLField(null=False, blank=False, default="http://example.com"),
                AnyUrl,
                FieldInfo(
                    default="http://example.com",
                    max_length=200,
                    pattern=URLValidator.regex,
                ),
            ),
            (
                models.URLField(null=True, blank=True),
                t.Optional[AnyUrl],
                FieldInfo(default=None, max_length=200, pattern=URLValidator.regex),
            ),
            (
                models.URLField(
                    null=True,
                    blank=False,
                    default="http://example.com",
                ),
                t.Optional[AnyUrl],
                FieldInfo(
                    default="http://example.com",
                    max_length=200,
                    pattern=URLValidator.regex,
                ),
            ),
        ]
    )
    def test_url_field_conversion(self, django_field, expected_type, expected_field):
        python_type, field = convert_db_field(django_field, optional=False)
        self.assertEqual(python_type, expected_type)
        self.assertPydanticFieldEqual(field, expected_field)

    # -------------------------------------------------------------
    # Date Fields (Date, DateTime, Time, Duration)
    # -------------------------------------------------------------

    @parameterized.expand(
        [
            (
                models.DateField(
                    verbose_name="my field",
                    help_text=" coucou ",
                ),
                datetime.date,
                FieldInfo(
                    title="My Field",
                    description="Coucou",
                ),
            ),
            (
                models.DateField(null=False, blank=False),
                datetime.date,
                FieldInfo(),
            ),
            (
                models.DateField(null=True, blank=True),
                t.Optional[datetime.date],
                FieldInfo(default=None),
            ),
            (
                models.DateField(
                    null=True,
                    blank=False,
                ),
                t.Optional[datetime.date],
                FieldInfo(
                    default=None,
                ),
            ),
        ]
    )
    def test_date_field_conversion(self, django_field, expected_type, expected_field):
        python_type, field = convert_db_field(django_field, optional=False)
        self.assertEqual(python_type, expected_type)
        self.assertPydanticFieldEqual(field, expected_field)

    @parameterized.expand(
        [
            (
                models.DateTimeField(
                    verbose_name="my field",
                    help_text=" coucou ",
                    default=timezone.now,
                ),
                datetime.datetime,
                FieldInfo(
                    title="My Field",
                    description="Coucou",
                    default_factory=timezone.now
                ),
            ),
            (
                models.DateTimeField(null=False, blank=False),
                datetime.datetime,
                FieldInfo(),
            ),
            (
                models.DateTimeField(null=True, blank=True),
                t.Optional[datetime.datetime],
                FieldInfo(default=None),
            ),
            (
                models.DateTimeField(
                    null=True,
                    blank=False,
                ),
                t.Optional[datetime.datetime],
                FieldInfo(
                    default=None,
                ),
            ),
        ]
    )
    def test_datetime_field_conversion(self, django_field, expected_type, expected_field):
        python_type, field = convert_db_field(django_field, optional=False)
        self.assertEqual(python_type, expected_type)
        self.assertPydanticFieldEqual(field, expected_field)

    @parameterized.expand(
        [
            (
                models.DurationField(
                    verbose_name="my field",
                    help_text=" coucou ",
                    default="01:00:00",
                ),
                datetime.timedelta,
                FieldInfo(title="My Field", description="Coucou", default="01:00:00"),
            ),
            (
                models.DurationField(null=False, blank=False),
                datetime.timedelta,
                FieldInfo(),
            ),
            (
                models.DurationField(null=True, blank=True),
                t.Optional[datetime.timedelta],
                FieldInfo(default=None),
            ),
            (
                models.DurationField(
                    null=True,
                    blank=False,
                ),
                t.Optional[datetime.timedelta],
                FieldInfo(
                    default=None,
                ),
            ),
        ]
    )
    def test_duration_field_conversion(self, django_field, expected_type, expected_field):
        python_type, field = convert_db_field(django_field, optional=False)
        self.assertEqual(python_type, expected_type)
        self.assertPydanticFieldEqual(field, expected_field)

    @parameterized.expand(
        [
            (
                models.TimeField(
                    verbose_name="my field",
                    help_text=" coucou ",
                    default="01:00:00",
                ),
                datetime.time,
                FieldInfo(title="My Field", description="Coucou", default="01:00:00"),
            ),
            (
                models.TimeField(null=False, blank=False),
                datetime.time,
                FieldInfo(),
            ),
            (
                models.TimeField(null=True, blank=True),
                t.Optional[datetime.time],
                FieldInfo(default=None),
            ),
            (
                models.TimeField(
                    null=True,
                    blank=False,
                ),
                t.Optional[datetime.time],
                FieldInfo(
                    default=None,
                ),
            ),
        ]
    )
    def test_time_field_conversion(self, django_field, expected_type, expected_field):
        python_type, field = convert_db_field(django_field, optional=False)
        self.assertEqual(python_type, expected_type)
        self.assertPydanticFieldEqual(field, expected_field)

    # -------------------------------------------------------------
    # Relational Fields (ForeignKey, OneToOne, ManyToMany)
    # -------------------------------------------------------------

    def test_foreign_key_field_conversion(self):
        pass  # TODO

    def test_many_to_many_field_conversion(self):
        pass  # TODO

    def test_one_to_many_field_conversion(self):
        pass  # TODO

    # -------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------

    def assertPydanticFieldEqual(self, expected_fieldinfo, given_fieldinfo):  # pylint: disable=invalid-name
        self.assertEqual(given_fieldinfo.default, expected_fieldinfo.default)
        self.assertEqual(given_fieldinfo.default_factory, expected_fieldinfo.default_factory)
        self.assertEqual(given_fieldinfo.title, expected_fieldinfo.title)
        self.assertEqual(given_fieldinfo.description, expected_fieldinfo.description)
        self.assertEqual(given_fieldinfo.alias, expected_fieldinfo.alias)

        given_metadata = self._extract_metadata_as_dict(given_fieldinfo)
        expected_metadata = self._extract_metadata_as_dict(expected_fieldinfo)

        self.assertDictEqual(given_metadata, expected_metadata)

    def _extract_metadata_as_dict(self, pydantic_field):
        values = {}
        metadata_attr_map = {
            Le: 'le',
            Lt: 'lt',
            Ge: 'ge',
            Gt: 'gt',
            MaxLen: 'max_length',
            MinLen: 'min_length',
        }
        general_metadata_attrs= ["max_digits", "decimal_places", "pattern"]
        for metadata in pydantic_field.metadata:
            is_general_metadata = True
            for metadata_class, attr in metadata_attr_map.items():
                if isinstance(metadata, metadata_class):
                    values[attr] = getattr(metadata, attr)
                    is_general_metadata = False
                # >>> f=FieldInfo(max_digits=33)
                # >>> f.metadata[0].__class__.__qualname__
                # '_general_metadata_cls.<locals>._PydanticGeneralMetadata'
                if is_general_metadata:
                    for attr in general_metadata_attrs:
                        if hasattr(metadata, attr):
                            values[attr] = getattr(metadata, attr)
        return values
