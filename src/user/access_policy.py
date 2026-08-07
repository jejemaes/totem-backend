import enum
from collections import namedtuple
from functools import reduce
from operator import and_, or_
from typing import List, Optional

from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.db.models import Q
from pydantic import BaseModel

from user.models import User

ALL_ACTIONS = '__all__'
BASE_RULE_ID = '__base_rule__'


class Context(BaseModel):
    user: Optional[User] = None
    # Roles of `user`, when the caller already has them. `None` means "not
    # provided, fetch them"; an empty list means "this user has no role".
    roles: Optional[list] = None

    class Config:
        arbitrary_types_allowed = True


# -------------------------------------------------------
# Access Rules Registry
# -------------------------------------------------------

WrappedRule = namedtuple('WrappedRule', 'rule roles')


class AccessPolicyRegistry:
    _instance = None

    _rule_registry = {} # identifier -> Rule instance
    _rule_model_registry = {} # model -> list rule instance

    def __new__(class_, *args, **kwargs):
        """Singleton pattern: ensure there is only one instance of this class. Call
        constructor `AccessPolicyRegistry()` will return the instance of it exsits,
        create it if not.
        """
        if not isinstance(class_._instance, class_):
            class_._instance = object.__new__(class_, *args, **kwargs)
        return class_._instance

    def register_rule(self, rule_cls):
        return self._register_rule(rule_cls)

    def _register_rule(self, rule_cls):
        if not issubclass(rule_cls.model, models.Model):
            raise ImproperlyConfigured(f"Rule class {rule_cls.__name__} must have a model defined.")
        if not isinstance(rule_cls.identifier, str):
            raise ImproperlyConfigured(f"Rule class {rule_cls.__name__} must have an identifier (string).")
        if rule_cls.identifier in self._rule_registry:
            raise ImproperlyConfigured(f"Rule class {rule_cls.__name__} has a non unique identifier.")
        if not rule_cls.name:
            raise ImproperlyConfigured(f"Rule class {rule_cls.__name__} must have a name.")

        rule = rule_cls()
        self._rule_registry[rule_cls.identifier] = rule
        self._rule_model_registry.setdefault(rule_cls.model, []).append(rule)

    def get_model_rules(self, model_cls):
        return self._rule_model_registry.get(
            model_cls, []
        )  # if no rule registered, should not crash

    def get_rules(self, *ids):
        return [rule for rid, rule in self._rule_registry.items() if rid in ids]

    def get_matching_rules(self, model_cls: models.Model, operation: str = None, rule_ids: List[str] = None):
        result = {}
        rules = self.get_model_rules(model_cls)

        for rule in rules:
            if operation is not None:
                if operation not in rule.operations:
                    continue
            if rule_ids is not None:
                if rule.identifier not in rule_ids:
                    continue
            result[rule.identifier] = rule

        return result

    def get_rule_choices(self, model_name_prefix=False):
        if model_name_prefix:
            return {rid: f"{rule.model._meta.verbose_name}: {rule.name}" for rid, rule in self._rule_registry.items()}
        return {rid: rule.name for rid, rule in self._rule_registry.items()}

    def get_all_rules(self):
        return self._rule_registry.values()


access_policy = AccessPolicyRegistry()  # singleton registry

# ------------------------------------------------------
# Access Rule
# ------------------------------------------------------

class CRUDOperation(enum.Enum):
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"


class BaseRuleMetaclass(type):
    def __new__(cls, name, bases, attrs):
        new_cls = type.__new__(cls, name, bases, attrs)
        if new_cls.identifier == BASE_RULE_ID:
            return new_cls
        access_policy.register_rule(new_cls)
        return new_cls


class BaseRule(metaclass=BaseRuleMetaclass):
    """
    A base class from which all rule classes should inherit.
    """
    identifier: str = BASE_RULE_ID
    model: models.Model = None # required
    name: str = None # required
    description: str = None

    # List of possible operations for this model. Goal is to avoid
    # too many imports. Depends on what is implemented in the
    # model service.
    operations = List[CRUDOperation]  # customize if needed

    def scope_filter(self, context: Context) -> Q:
        """Return the lookups to apply on filter. Must be a `Q` expression."""
        return Q()

# ------------------------------------------------------
# API
# ------------------------------------------------------

async def request_to_context(request):
    user = None  # force none instead of Anonymous user
    if request.auth and hasattr(request.auth, "user"):
        user = request.auth.user
    return Context(user=user)


async def apply_access_rules(queryset: models.QuerySet, operation: str, context: Context):
    """ Apply access rules for the given model and apply them on
        current queryset to scope it.
        Assembled as (Role1_ruleA & Role1_ruleB) || (Role2_rule2 & Role2_rule4)
        :param queryset: django queryset to alter
        :param action: operation (string) to check
    """
    # Extract role of current context (API token ignores role rules)
    roles = context.roles
    if roles is None:
        roles = []
        if context.user:
            roles = [userrole async for userrole in context.user.roles.all()]

    rule_groups = []
    for role in roles:
        rule_groups.append(list(role.rules) if role.rules is not None else list())

    # Flatten list to find rule to apply
    role_rule_ids = [element for innerList in rule_groups for element in innerList]
    matching_rule_maps = access_policy.get_matching_rules(queryset.model, operation=operation, rule_ids=role_rule_ids)

    # Combine role rules with logical AND
    lookups = []
    for role_rules in rule_groups:
        q_expr = Q()
        for rule_id in role_rules:
            rule_to_apply = matching_rule_maps.get(rule_id)
            if rule_to_apply:
                q_expr = q_expr & rule_to_apply.scope_filter(context)

        if q_expr:
            lookups.append(q_expr)

    # Combine Q-lookups with logical OR
    if lookups:
        rule_lookup = reduce(or_, lookups)
        if rule_lookup:
            queryset = queryset.filter(rule_lookup)

    return queryset
