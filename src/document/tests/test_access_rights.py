import json
from pathlib import Path

from django.test import SimpleTestCase

from user.access_rights import get_all_permission

ROLES_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "system" / "user_roles.json"


class DocumentRolesTest(SimpleTestCase):
    """ The roles shipped. No rule is registered for the documents, so the roles
    differ by their scopes alone, which the controllers check. """

    def roles(self):
        return {
            item["pk"]: set(json.loads(item["fields"]["permissions"]))
            for item in json.loads(ROLES_FIXTURE.read_text())
        }

    def test_every_scope_granted_is_registered(self):
        registered = {permission for permission, _ in get_all_permission()}
        for pk, permissions in self.roles().items():
            self.assertLessEqual(permissions, registered, pk)

    def test_user_reads_the_tags_and_manages_the_documents(self):
        self.assertEqual(
            self.roles()["DOCUMENT_USER"],
            {
                "totem.document.create",
                "totem.document.read",
                "totem.document.update",
                "totem.document.delete",
                "totem.documenttag.read",
                "totem.documenttagcategory.read",
            },
        )

    def test_manager_manages_everything(self):
        self.assertEqual(
            self.roles()["DOCUMENT_MANAGER"],
            {
                f"totem.{model}.{operation}"
                for model in ("document", "documenttag", "documenttagcategory")
                for operation in ("create", "read", "update", "delete")
            },
        )
