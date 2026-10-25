"""SQL expressions of our own, for what django does not provide.

The extension point of `GroupByMixin` (`core.services.group_by`): a custom
aggregate is a `Func`, an `Aggregate` or a `Window` here, wrapped in a `Measure`.
`group_by` itself never changes for one.
"""

from django.db.models import F, Sum, Window
from django.db.models.expressions import ExpressionList, Func


class _RawSum(Func):
    """Plain `SUM(...)`, deliberately not an `Aggregate` subclass so it can be
    nested inside another aggregate: django refuses `Sum(Sum(...))` ("'Sum' is an
    aggregate")."""

    function = "SUM"


class SumOverGroups(Window):
    """`SUM(SUM(field)) OVER (PARTITION BY <every group key except exclude>)`.

    Meant for "share of a total" measures in a `values(*keys).annotate(...)` query,
    from insights (`base/orm/functions.py`). In a grouped query a window function
    runs over the *grouped* rows, hence the double SUM: the inner one is the
    aggregate of each group, the outer one adds the totals of the groups across the
    partition.

    The partition is read from the query being resolved -- its `values()` fields,
    plus its selected non-aggregate annotations, the date truncations of a group by
    -- so one declaration serves whatever group keys a client asks for. With every
    key excluded, or none at all, the window is `OVER ()`: the grand total.

    Relies on django internals (`Query.values_select`, `Query.annotation_select`,
    `get_group_by_cols`, `get_refs`): `core.tests.test_orm.test_functions` is what
    tells an upgrade broke them.
    """

    # Computed over aggregated rows: flagged as containing an aggregate, so that
    # django puts neither it nor what wraps it (a `NullIf`, a `Cast`) in the GROUP BY.
    contains_aggregate = True

    def __init__(self, field_name, exclude=()):
        self.exclude = tuple(exclude)
        super().__init__(expression=Sum(_RawSum(F(field_name))))

    def resolve_expression(
        self, query=None, allow_joins=True, reuse=None, summarize=False, for_save=False
    ):
        names = list(query.values_select)
        for alias, annotation in query.annotation_select.items():
            if not annotation.contains_aggregate and not annotation.contains_over_clause:
                names.append(alias)
        partition = [F(name) for name in names if name not in self.exclude]
        # On a copy: a measure is declared once, on the service class, and resolved
        # by every query. The partition belongs to one query only.
        clone = self.copy()
        clone.partition_by = ExpressionList(*partition) if partition else None
        return super(SumOverGroups, clone).resolve_expression(
            query, allow_joins, reuse, summarize, for_save
        )

    def get_group_by_cols(self):
        # The partition columns are grouped already, through `values()`.
        return []

    def get_refs(self):
        # `Window` keeps None for an unset partition, order or frame: skipped.
        return set().union(
            *(
                expression.get_refs()
                for expression in self.get_source_expressions()
                if expression is not None
            )
        )
