from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models.expressions import RawSQL

from core.orm.validators import validate_unique_choice_array
from user import signals
from user.access_policy import access_policy
from user.access_rights import get_all_permission
from user.models import User

# ---------------------------------------------------------------
# User Role
# ---------------------------------------------------------------

def get_rule_choices():
    return access_policy.get_rule_choices()


class UserRole(models.Model):
    id = models.CharField(
        "ID", max_length=128, null=False, blank=False, primary_key=True)
    name = models.CharField(
        "Name", max_length=255, null=False, blank=False)
    permissions = ArrayField(
        models.CharField(max_length=128, blank=False, choices=get_all_permission),
        blank=True,
        default=list,
        validators=[validate_unique_choice_array],
        help_text="List of permissions available for this role."
    )
    rules = ArrayField(
        models.CharField(max_length=128, blank=False, choices=get_rule_choices),
        blank=True,
        default=list,
        validators=[validate_unique_choice_array],
        help_text="List of access rules applied for this role."
    )

    class Meta:
        verbose_name = "User Role"
        verbose_name_plural = "User Roles"


# ---------------------------------------------------------------
# User Role Relation
# ---------------------------------------------------------------

class UserRoleRelationQuerySet(models.QuerySet):

    def bulk_create(
        self,
        objs,
        batch_size=None,
        ignore_conflicts=False,
        update_conflicts=False,
        update_fields=None,
        unique_fields=None,
    ):
        results = super().bulk_create(objs, batch_size=batch_size, ignore_conflicts=ignore_conflicts, update_conflicts=update_conflicts, update_fields=update_fields, unique_fields=unique_fields)
        if results:
            user_pks = [rel.user_id for rel in results]
            signals.user_change_rights.send(sender=self.__class__, user_qs=User.objects.filter(pk__in=user_pks))
        return results

    def update(self, **kwargs):
        user_pks = None
        if 'role' in kwargs:
            if (
                self._result_cache is None
            ):  # queryset not evaluated, fetch only required fields
                user_pks = self.values_list('user_id', flat=True)
            else:  # queryset already evaluated
                user_pks = [rel.user_id for rel in self]

        results = super().update(**kwargs)

        if user_pks:
            signals.user_change_rights.send(sender=self.__class__, user_qs=User.objects.filter(pk__in=user_pks))

        return results

    def delete(self):
        user_pks = [rel.user_id for rel in self]
        results = super().delete()
        if user_pks:
            signals.user_change_rights.send(sender=self.__class__, user_qs=User.objects.filter(pk__in=user_pks))
        return results


class UserRoleRelation(models.Model):
    user = models.ForeignKey(
        'user.User', related_name='role_relations', null=False, on_delete=models.CASCADE)
    role = models.ForeignKey(
        'user.UserRole', related_name='role_relations', null=False, on_delete=models.CASCADE)

    objects = UserRoleRelationQuerySet.as_manager()

    class Meta:
        indexes = []
        constraints = [
            models.UniqueConstraint(
                RawSQL("""SPLIT_PART("role_id", '_', 1)""", params=[],
                       output_field=models.CharField()), "user",
                name="unique_role_category",
                violation_error_message="A user can only have one role per category.",
            ),
        ]

    def save(self, *args, **kwargs):
        update_fields = kwargs.get('update_fields')
        super().save(*args, **kwargs)
        if update_fields is None or 'role' in update_fields:
            signals.user_change_rights.send(sender=self.__class__, user_qs=User.objects.filter(pk=self.user_id))

    def delete(self, using=None, keep_parents=False):
        user_id = self.user_id
        super().delete(using=using, keep_parents=keep_parents)
        signals.user_change_rights.send(sender=self.__class__, user_qs=User.objects.filter(pk=user_id))
