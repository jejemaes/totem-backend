from django.db.models import Model, Q

from user.access_policy import BaseRule
from user.access_rights import register_permission

from account.models import Budget, BudgetLine, BudgetPosition

# ---------------------------------------------------------
# Define Scopes
# ---------------------------------------------------------

register_permission("totem.account.create", "Create Accounts", is_public=True)
register_permission("totem.account.read", "Read Accounts", is_public=True)
register_permission("totem.account.update", "Update Accounts", is_public=True)
register_permission("totem.account.delete", "Delete Accounts", is_public=True)

register_permission("totem.accountcategory.create", "Create Account Categories", is_public=True)
register_permission("totem.accountcategory.read", "Read Account Categories", is_public=True)
register_permission("totem.accountcategory.update", "Update Account Categories", is_public=True)
register_permission("totem.accountcategory.delete", "Delete Account Categories", is_public=True)

register_permission("totem.accountmovement.create", "Create Account Movements", is_public=True)
register_permission("totem.accountmovement.read", "Read Account Movements", is_public=True)
register_permission("totem.accountmovement.update", "Update Account Movements", is_public=True)
register_permission("totem.accountmovement.delete", "Delete Account Movements", is_public=True)

register_permission("totem.budget.create", "Create Budgets", is_public=True)
register_permission("totem.budget.read", "Read Budgets", is_public=True)
register_permission("totem.budget.update", "Update Budgets", is_public=True)
register_permission("totem.budget.delete", "Delete Budgets", is_public=True)

# ---------------------------------------------------------
# Access rules
# ---------------------------------------------------------

# None on accounts, categories and movements: whoever holds a scope reaches all
# of them.
#
# The budgets have one rule per model and per reach. The positions and lines are
# scoped through their budget (`BudgetLine.budget` is stored for that), so a user
# limited to their budgets reaches neither the positions nor the lines of another.
#
# The "all" rules are not decorative: `apply_access_rules` ORs the roles of a
# user, and a role granting no rule on a model adds nothing to that OR. Without
# them, an administrator who also held a role granting an "own" rule would be
# narrowed to their own budgets.


class BudgetManageOwnRule(BaseRule):
    identifier: str = "budget_manage_own"
    model: Model = Budget
    name: str = "Manage Own Budgets"
    description: str = "Only the budgets you are in charge of."
    operations = ["create", "read", "update", "delete"]

    def scope_filter(self, context) -> Q:
        if context.user:
            return Q(user_id=context.user.pk)
        return Q()


class BudgetPositionManageOwnRule(BaseRule):
    identifier: str = "budget_position_manage_own"
    model: Model = BudgetPosition
    name: str = "Manage Positions of Own Budgets"
    description: str = "Only the positions of the budgets you are in charge of."
    operations = ["create", "read", "update", "delete"]

    def scope_filter(self, context) -> Q:
        if context.user:
            return Q(budget__user_id=context.user.pk)
        return Q()


class BudgetLineManageOwnRule(BaseRule):
    identifier: str = "budget_line_manage_own"
    model: Model = BudgetLine
    name: str = "Manage Lines of Own Budgets"
    description: str = "Only the lines of the budgets you are in charge of."
    operations = ["create", "read", "update", "delete"]

    def scope_filter(self, context) -> Q:
        if context.user:
            return Q(budget__user_id=context.user.pk)
        return Q()


class BudgetManageAllRule(BaseRule):
    identifier: str = "budget_manage_all"
    model: Model = Budget
    name: str = "Manage All Budgets"
    description: str = "Every budget, whoever is in charge of it."
    operations = ["create", "read", "update", "delete"]

    def scope_filter(self, context) -> Q:
        return ~Q(pk__in=[])  # always true


class BudgetPositionManageAllRule(BaseRule):
    identifier: str = "budget_position_manage_all"
    model: Model = BudgetPosition
    name: str = "Manage Positions of All Budgets"
    description: str = "The positions of every budget."
    operations = ["create", "read", "update", "delete"]

    def scope_filter(self, context) -> Q:
        return ~Q(pk__in=[])  # always true


class BudgetLineManageAllRule(BaseRule):
    identifier: str = "budget_line_manage_all"
    model: Model = BudgetLine
    name: str = "Manage Lines of All Budgets"
    description: str = "The lines of every budget."
    operations = ["create", "read", "update", "delete"]

    def scope_filter(self, context) -> Q:
        return ~Q(pk__in=[])  # always true
