from django.db import models


class WidgetPosition(models.TextChoices):
    FOOTER_1 = 'FOOTER_1', 'Footer 1'
    FOOTER_2 = 'FOOTER_2', 'Footer 2'
    FOOTER_3 = 'FOOTER_3', 'Footer 3'
    FOOTER_4 = 'FOOTER_4', 'Footer 4'

    HOMEPAGE_1 = 'HOMEPAGE_1', 'Homepage 1'
    HOMEPAGE_2 = 'HOMEPAGE_2', 'Homepage 2'
    HOMEPAGE_3 = 'HOMEPAGE_3', 'Homepage 3'
    HOMEPAGE_4 = 'HOMEPAGE_4', 'Homepage 4'


# A position encodes the area it belongs to as a prefix, and a view selects a
# whole area with it. Named here rather than spelled as a literal in each view,
# which is how `'FOOTER_'` and `'HOMEPAGE_'` ended up in three places. Module
# constants and *not* members of `WidgetPosition`: a bare attribute on a
# `TextChoices` becomes a choice, so they would land in `Widget.position`'s
# choices, generate a migration, and let a payload set `position='FOOTER_'`.
WIDGET_POSITION_FOOTER_PREFIX = 'FOOTER_'
WIDGET_POSITION_HOMEPAGE_PREFIX = 'HOMEPAGE_'
