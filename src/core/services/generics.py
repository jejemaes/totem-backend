"""Read back the generic parameters a service subclass declared.

Python erases generic parameters at runtime: writing `ServiceBase[User]` installs
no attribute and checks nothing. Method bodies however need real classes
(`self.model(**values)`), so the parametrization has to be materialized as
ordinary class attributes. These helpers extract it from `__orig_bases__` so that
`__init_subclass__` can do that materialization once, at class definition time.
"""

import typing as t


def generic_args_for(cls: type, origin: type) -> t.Optional[t.Tuple]:
    """Return the arguments `cls` passed to the generic `origin`, or None.

    Walks the MRO so intermediate inheritance keeps working: a subclass that
    subscripts nothing itself carries no `origin[...]` of its own, the
    parametrization lives on one of its ancestors.
    """
    for klass in cls.__mro__:
        # Read `__orig_bases__` from `__dict__` rather than with `getattr`: the
        # attribute is inherited, so `getattr` on a class that does not subscript
        # anything would report its parent's parametrization as its own.
        for base in klass.__dict__.get("__orig_bases__", ()):
            if t.get_origin(base) is origin:
                return t.get_args(base)
    return None


def is_concrete(args: t.Iterable) -> bool:
    """Whether every generic argument is resolved to an actual class.

    `ForwardRef` counts as unresolved: a module using `from __future__ import
    annotations` yields string annotations that `get_args` cannot resolve, and
    treating them as concrete would silently store a `ForwardRef` as `cls.model`.
    """
    return not any(isinstance(arg, (t.TypeVar, t.ForwardRef)) for arg in args)


def check_concrete(cls: type, origin: type, args: t.Iterable) -> bool:
    """Return True when `args` are usable, False when `cls` is still generic.

    A subclass may legitimately stay generic (an abstract intermediate service
    parametrized by its own TypeVars); it just has nothing to materialize yet, so
    we report False instead of raising. Unresolved arguments on a class that
    presents itself as concrete are a definition error and raise at import time,
    which is the whole point of doing this in `__init_subclass__` rather than
    lazily on first access.
    """
    args = tuple(args)
    if is_concrete(args):
        return True
    if getattr(cls, "__parameters__", ()):
        return False
    unresolved = [arg for arg in args if not is_concrete([arg])]
    raise TypeError(
        f"{cls.__name__} does not fully parametrize {origin.__name__}: "
        f"{unresolved!r} left unresolved."
    )
