from uuid import UUID

from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from core.services.exceptions import ServiceValidationMultiError
from core.testing import ServiceTestCaseMixin
from user import choices as user_choices
from user.models import User, UserRole
from user.schemas import UserCreateSchema, UserUpdateSchema
from user.services import UserService

from user.tests.test_services.common_user import (
    ROLE_HOBBIT_ID,
    ROLE_ORC_ID,
    ROLE_WIZARD_ID,
    USER_FRODON_ID,
    USER_GOLLUM_ID,
    USER_SAM_ID,
    UserServiceCommonMixin,
)

ALL_USER_IDS = [USER_FRODON_ID, USER_GOLLUM_ID, USER_SAM_ID]


class UserServiceTest(UserServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `UserService`: create, read, update, delete and default values.

    The relations resolved out of scope are in `test_relation_resolution`, which
    needs a rule on `UserRole` of its own.
    """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(UserService, user=self.user_frodon)

    # ------------------------------------------
    # Create
    # ------------------------------------------

    @parameterized.expand(
        [
            (
                "without role",
                {"login": "pipin@lacomte.com", "email": "pipin@lacomte.com", "roles": []},
                5,
                {"user_type": "PORTAL", "language": "fr"},
                [],
            ),
            (
                "with a role",
                {"login": "pipin@lacomte.com", "email": "pipin@lacomte.com", "roles": [ROLE_HOBBIT_ID]},
                8,
                {"user_type": "PORTAL", "language": "fr"},
                [ROLE_HOBBIT_ID],
            ),
            (
                "with two roles of distinct categories",
                {
                    "login": "pipin@lacomte.com",
                    "email": "pipin@lacomte.com",
                    "roles": [ROLE_HOBBIT_ID, ROLE_ORC_ID],
                    "user_type": "INTERNAL",
                    "language": "en-us",
                    "first_name": "Peregrin",
                },
                8,
                {"user_type": "INTERNAL", "language": "en-us", "first_name": "Peregrin"},
                [ROLE_HOBBIT_ID, ROLE_ORC_ID],
            ),
            (
                # The email is no key: only the login is unique.
                "with the email of another user",
                {"login": "pipin@lacomte.com", "email": "frodon@lacomte.com", "roles": []},
                5,
                {"email": "frodon@lacomte.com"},
                [],
            ),
        ]
    )
    def test_create(self, label, payload, query_count, expected_values, expected_roles):
        with self.assertNumQueries(query_count):
            instances = async_to_sync(self.service.create)([UserCreateSchema(**payload)])

        self.assertEqual(len(instances), 1)
        user = User.objects.get(pk=instances[0].pk)
        self.assertEqual(user.username, payload["login"])
        self.assertEqual({name: getattr(user, name) for name in expected_values}, expected_values)
        self.assertCountEqual(user.roles.values_list("id", flat=True), expected_roles)

    @parameterized.expand(
        [
            (
                "login taken",
                {"login": "frodon@lacomte.com", "email": "frodon2@lacomte.com", "roles": []},
                5,
                "A user with that username already exists.",
            ),
            (
                # The constraint is on the relation, not on `User`: its
                # `violation_error_message` is not found, and the raw database
                # error is handed back instead. Pinned as found.
                "two roles of one category",
                {"login": "pipin@lacomte.com", "email": "pipin@lacomte.com", "roles": [ROLE_HOBBIT_ID, ROLE_WIZARD_ID]},
                9,
                "A global validation error occurred: ",
            ),
        ]
    )
    def test_create_invalid(self, label, payload, query_count, message):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.create)([UserCreateSchema(**payload)])

        # A database constraint is reported for the whole batch, under no index.
        errors = ctx.exception.dict()
        self.assertEqual(list(errors), ["__all__"])
        self.assertEqual(len(errors["__all__"]["__all__"]), 1)
        self.assertTrue(errors["__all__"]["__all__"][0].startswith(message), errors)
        self.assertEqual(User.objects.count(), 3)

    def test_create_refuses_a_dict(self):
        # The schema is what guarantees the types and the required fields: a dict
        # carries no guarantee, and costs no query to refuse.
        data = {"login": "pipin@lacomte.com", "email": "pipin@lacomte.com", "roles": []}
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.create)([data])

        self.assertEqual(User.objects.count(), 3)

    @parameterized.expand(
        [
            # Resolved before the transaction opens: the roles of the acting
            # user, then the roles asked.
            ("unknown role", ["SHIRE_UNKNOWN"], 2),
            ("one known, one unknown", [ROLE_HOBBIT_ID, "SHIRE_UNKNOWN"], 2),
        ]
    )
    def test_create_relations(self, label, roles, query_count):
        data = UserCreateSchema(login="pipin@lacomte.com", email="pipin@lacomte.com", roles=roles)
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.create)([data])

        self.assertEqual(list(ctx.exception.dict()[0]), ["roles"])
        self.assertFalse(User.objects.filter(username="pipin@lacomte.com").exists())

    @parameterized.expand(
        [
            (
                "every input valid",
                [
                    {"login": "pipin@lacomte.com", "email": "pipin@lacomte.com", "roles": [ROLE_HOBBIT_ID]},
                    {"login": "merry@lacomte.com", "email": "merry@lacomte.com", "roles": [ROLE_HOBBIT_ID]},
                ],
                10,
                None,
            ),
            (
                # All or nothing: the valid first input is not written either.
                "the second input invalid",
                [
                    {"login": "pipin@lacomte.com", "email": "pipin@lacomte.com", "roles": [ROLE_HOBBIT_ID]},
                    {"login": "merry@lacomte.com", "email": "merry@lacomte.com", "roles": ["SHIRE_UNKNOWN"]},
                ],
                2,
                {1: ["roles"]},
            ),
        ]
    )
    def test_create_batch(self, label, payloads, query_count, errors):
        data = [UserCreateSchema(**payload) for payload in payloads]
        logins = [payload["login"] for payload in payloads]

        with self.assertNumQueries(query_count):
            if errors is None:
                instances = async_to_sync(self.service.create)(data)
            else:
                with self.assertRaises(ServiceValidationMultiError) as ctx:
                    async_to_sync(self.service.create)(data)

        if errors is None:
            self.assertEqual([user.username for user in instances], logins)
            self.assertEqual(User.objects.filter(username__in=logins).count(), 2)
        else:
            self.assertEqual({key: list(value) for key, value in ctx.exception.dict().items()}, errors)
            self.assertFalse(User.objects.filter(username__in=logins).exists())

    @parameterized.expand(
        [
            ("every field", None, {"user_type": "PORTAL", "language": "fr"}),
            ("the fields asked", ["language"], {"language": "fr"}),
            ("a field with no default", ["email"], {}),
            ("an unknown field is ignored", ["mithril"], {}),
        ]
    )
    def test_default_values(self, label, fields, expected):
        with self.assertNumQueries(0):
            values = async_to_sync(self.service.default_values)(fields)

        self.assertEqual({name: value for name, value in values.items() if value is not None}, expected)

    @parameterized.expand(
        [
            ("no rule", [], True),
            # `user_manage_own_profile` covers neither create nor delete: it holds
            # nothing back here.
            ("own profile", ["user_manage_own_profile"], True),
            ("all users", ["user_manage_all_user"], True),
            ("both, combined with AND", ["user_manage_own_profile", "user_manage_all_user"], True),
            ("anonymous: no role, no rule", None, True),
        ]
    )
    def test_create_access_rules(self, label, rules, created):
        service = self.service_with_rules(rules)
        data = UserCreateSchema(login="pipin@lacomte.com", email="pipin@lacomte.com", roles=[])

        instances = async_to_sync(service.create)([data])

        self.assertEqual(len(instances), 1)
        self.assertEqual(User.objects.filter(username="pipin@lacomte.com").exists(), created)

    # ------------------------------------------
    # Read
    # ------------------------------------------

    @parameterized.expand(
        [
            ("no filter", {}, ALL_USER_IDS),
            ("by login", {"username": "frodon@lacomte.com"}, [USER_FRODON_ID]),
            ("by pks", {"id__in": [USER_GOLLUM_ID, USER_SAM_ID]}, [USER_GOLLUM_ID, USER_SAM_ID]),
            ("by role", {"roles": ROLE_ORC_ID}, [USER_GOLLUM_ID]),
            ("by type", {"user_type": "INTERNAL"}, [USER_FRODON_ID, USER_SAM_ID]),
            ("nothing matches", {"username": "sauron@mordor.com"}, []),
        ]
    )
    def test_read_filters(self, label, filters, expected_pks):
        # The roles of the acting user, then the users.
        with self.assertNumQueries(2):
            pks = [str(user.pk) for user in async_to_sync(self.service.read)(filters)]

        self.assertCountEqual(pks, expected_pks)

    @parameterized.expand(
        [
            ("by login", ["username"], [USER_FRODON_ID, USER_GOLLUM_ID, USER_SAM_ID]),
            ("by login, descending", ["-username"], [USER_SAM_ID, USER_GOLLUM_ID, USER_FRODON_ID]),
            ("by type, then login", ["user_type", "-username"], [USER_SAM_ID, USER_FRODON_ID, USER_GOLLUM_ID]),
        ]
    )
    def test_read_ordering(self, label, ordering, expected_pks):
        with self.assertNumQueries(2):
            pks = [str(user.pk) for user in async_to_sync(self.service.read)(ordering=ordering)]

        self.assertEqual(pks, expected_pks)

    @parameterized.expand(
        [
            ("plain fields", ["id", "username"], 2, {"username"}),
            # The roles are prefetched: reading them afterwards costs nothing.
            ("with the roles", ["id", "username", "roles"], 3, {"username"}),
            ("the roles alone", ["id", "roles"], 3, set()),
        ]
    )
    def test_read_fields(self, label, fields, query_count, loaded):
        with self.assertNumQueries(query_count):
            users = list(async_to_sync(self.service.read)({"id": USER_GOLLUM_ID}, fields=fields))
            roles = [role.pk for role in users[0].roles.all()] if "roles" in fields else None

        self.assertEqual(len(users), 1)
        self.assertFalse(loaded & users[0].get_deferred_fields())
        self.assertIn("email", users[0].get_deferred_fields())
        if roles is not None:
            self.assertEqual(roles, [ROLE_ORC_ID])

    @parameterized.expand(
        [
            ("no rule", [], None, ALL_USER_IDS),
            ("own profile", ["user_manage_own_profile"], None, [USER_FRODON_ID]),
            ("all users", ["user_manage_all_user"], None, ALL_USER_IDS),
            ("both, combined with AND", ["user_manage_own_profile", "user_manage_all_user"], None, [USER_FRODON_ID]),
            ("two roles, combined with OR", ["user_manage_own_profile"], ["user_manage_all_user"], ALL_USER_IDS),
            # A second role with no rule widens nothing: a role contributes no
            # condition at all, rather than an always-true one. By design, hence
            # the always-true `user_manage_all_user` (see `account.security`).
            ("a second role without rule", ["user_manage_own_profile"], [], [USER_FRODON_ID]),
            ("anonymous: no role, no rule", None, None, ALL_USER_IDS),
        ]
    )
    def test_read_access_rules(self, label, rules, second_role_rules, expected_pks):
        service = self.service_with_rules(rules, second_role_rules)

        pks = [str(user.pk) for user in async_to_sync(service.read)()]

        self.assertCountEqual(pks, expected_pks)

    # ------------------------------------------
    # Update
    # ------------------------------------------

    @parameterized.expand(
        [
            (
                "a plain field",
                {"email": "gollum@misty-mountains.com"},
                5,
                {"email": "gollum@misty-mountains.com", "first_name": "Sméagol"},
                [ROLE_ORC_ID],
            ),
            (
                "the login, through its alias",
                {"login": "smeagol@precious.com"},
                5,
                {"username": "smeagol@precious.com"},
                [ROLE_ORC_ID],
            ),
            (
                "the roles are replaced",
                {"roles": [ROLE_HOBBIT_ID]},
                9,
                {"email": "gollum@precious.com"},
                [ROLE_HOBBIT_ID],
            ),
            (
                "the roles are emptied",
                {"roles": []},
                7,
                {"email": "gollum@precious.com"},
                [],
            ),
            (
                "a field set to null",
                {"first_name": None},
                5,
                {"first_name": None},
                [ROLE_ORC_ID],
            ),
        ]
    )
    def test_update(self, label, payload, query_count, expected_values, expected_roles):
        with self.assertNumQueries(query_count):
            count, queryset = async_to_sync(self.service.update)({"id": USER_GOLLUM_ID}, UserUpdateSchema(**payload))

        self.assertEqual(count, 1)
        self.assertEqual([str(user.pk) for user in queryset], [USER_GOLLUM_ID])
        user = User.objects.get(pk=USER_GOLLUM_ID)
        self.assertEqual({name: getattr(user, name) for name in expected_values}, expected_values)
        self.assertCountEqual(user.roles.values_list("id", flat=True), expected_roles)

    def test_update_partial(self):
        # Only the fields set are written: the others keep their stored value.
        async_to_sync(self.service.update)({"id": USER_SAM_ID}, UserUpdateSchema(first_name="Sam"))

        user = User.objects.get(pk=USER_SAM_ID)
        self.assertEqual(
            (user.first_name, user.last_name, user.language, user.user_type),
            ("Sam", "Gamgee", "en-us", user_choices.UserType.INTERNAL),
        )

    @parameterized.expand(
        [
            # Resolved before any row is read: keyed by the index of the payload.
            ("unknown role", {"roles": ["SHIRE_UNKNOWN"]}, 2, {0: ["roles"]}),
            # Database constraints: keyed on nobody. See `test_create_invalid`
            # about the raw message of the roles.
            ("two roles of one category", {"roles": [ROLE_HOBBIT_ID, ROLE_WIZARD_ID]}, 10, {"__all__": None}),
            ("login taken", {"login": "frodon@lacomte.com"}, 6, {"__all__": None}),
        ]
    )
    def test_update_invalid(self, label, payload, query_count, errors):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.update)({"id": USER_GOLLUM_ID}, UserUpdateSchema(**payload))

        self.assertEqual(
            {key: list(value) if errors[key] else None for key, value in ctx.exception.dict().items()},
            errors,
        )
        user = User.objects.get(pk=USER_GOLLUM_ID)
        self.assertEqual(user.username, "gollum@precious.com")
        self.assertEqual(list(user.roles.values_list("id", flat=True)), [ROLE_ORC_ID])

    def test_update_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.update)({"id": USER_GOLLUM_ID}, {"email": "gollum@mordor.com"})

        self.assertEqual(User.objects.get(pk=USER_GOLLUM_ID).email, "gollum@precious.com")

    def test_update_batch(self):
        with self.assertNumQueries(5):
            count, queryset = async_to_sync(self.service.update)(
                {"user_type": "INTERNAL"}, UserUpdateSchema(language="fr")
            )

        self.assertEqual(count, 2)
        self.assertCountEqual([str(user.pk) for user in queryset], [USER_FRODON_ID, USER_SAM_ID])
        self.assertEqual(
            dict(User.objects.values_list("username", "language")),
            {"frodon@lacomte.com": "fr", "gollum@precious.com": "fr", "sam@lacomte.com": "fr"},
        )

    def test_update_not_found(self):
        with self.assertNumQueries(4):
            count, queryset = async_to_sync(self.service.update)(
                {"username": "sauron@mordor.com"}, UserUpdateSchema(language="en-us")
            )

        self.assertEqual((count, list(queryset)), (0, []))
        self.assertFalse(User.objects.filter(language="en-us").exclude(pk=USER_SAM_ID).exists())

    @parameterized.expand(
        [
            ("no rule", [], None, True),
            ("own profile", ["user_manage_own_profile"], None, False),
            ("all users", ["user_manage_all_user"], None, True),
            ("both, combined with AND", ["user_manage_own_profile", "user_manage_all_user"], None, False),
            ("two roles, combined with OR", ["user_manage_own_profile"], ["user_manage_all_user"], True),
            ("anonymous: no role, no rule", None, None, True),
        ]
    )
    def test_update_access_rules(self, label, rules, second_role_rules, reached):
        service = self.service_with_rules(rules, second_role_rules)

        count, queryset = async_to_sync(service.update)(
            {"id": USER_GOLLUM_ID}, UserUpdateSchema(email="gollum@mordor.com")
        )

        # Out of reach is no error: the row is not matched.
        self.assertEqual(count, int(reached))
        self.assertEqual(User.objects.get(pk=USER_GOLLUM_ID).email == "gollum@mordor.com", reached)

    # ------------------------------------------
    # Delete
    # ------------------------------------------

    @parameterized.expand(
        [
            # Each table pointing at the user costs a query: the role relations,
            # the refresh tokens (cascade), `Budget.user`, `Document.user` and
            # `Page.user` (set null). This count moves with every new relation to
            # the user, which is what it is meant to tell.
            ("a user without role", {"id": USER_SAM_ID}, 14, 1, [USER_FRODON_ID, USER_GOLLUM_ID]),
            ("a user with a role", {"id": USER_GOLLUM_ID}, 14, 1, [USER_FRODON_ID, USER_SAM_ID]),
            ("several users", {"user_type": "INTERNAL"}, 14, 2, [USER_GOLLUM_ID]),
            ("nothing matches", {"username": "sauron@mordor.com"}, 5, 0, ALL_USER_IDS),
        ]
    )
    def test_delete(self, label, filters, query_count, affected, remaining_pks):
        with self.assertNumQueries(query_count):
            count = async_to_sync(self.service.delete)(filters)

        self.assertEqual(count, affected)
        self.assertCountEqual([str(pk) for pk in User.objects.values_list("pk", flat=True)], remaining_pks)
        # The relations to the roles go with the user, the roles stay.
        self.assertEqual(UserRole.objects.count(), 4)
        self.assertFalse(User.roles.through.objects.exclude(user_id__in=remaining_pks).exists())

    @parameterized.expand(
        [
            ("no rule", [], None, True),
            # `user_manage_own_profile` does not cover delete: it holds nothing back.
            ("own profile", ["user_manage_own_profile"], None, True),
            ("all users", ["user_manage_all_user"], None, True),
            ("both, combined with AND", ["user_manage_own_profile", "user_manage_all_user"], None, True),
            ("anonymous: no role, no rule", None, None, True),
        ]
    )
    def test_delete_access_rules(self, label, rules, second_role_rules, reached):
        service = self.service_with_rules(rules, second_role_rules)

        count = async_to_sync(service.delete)({"id": USER_GOLLUM_ID})

        self.assertEqual(count, int(reached))
        self.assertEqual(User.objects.filter(pk=USER_GOLLUM_ID).exists(), not reached)

    # ------------------------------------------
    # Utils
    # ------------------------------------------

    def service_with_rules(self, rules, second_role_rules=None):
        """ The service acting as Frodon, whose role holds `rules`; with
        `second_role_rules`, Frodon holds a second role with those. `rules=None`
        is an anonymous caller."""
        if rules is None:
            return self.get_service(UserService)
        self.role.rules = rules
        self.role.save()
        if second_role_rules is not None:
            self.role_hobbit.rules = second_role_rules
            self.role_hobbit.save()
            self.user_frodon.roles.add(self.role_hobbit)
        return self.get_service(UserService, user=self.user_frodon)
