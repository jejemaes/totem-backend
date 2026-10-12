import os
import textwrap

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from base.choices import FileReferencePrivacy
from base.files.storages import PublicMediaFileSystemStorage
from core.db.tenancy import validate_database_name


class Command(BaseCommand):
    help = textwrap.dedent(
        """
        Move the media of a single-tenant deployment under the root of its database.

        Before: MEDIA_ROOT/{_filestore,public,private}, with absolute symlinks.
        After:  MEDIA_ROOT/<db_name>/{_filestore,public,private}, with relative ones.

        Run once, with the services stopped. Moving is a rename (same file
        system), so nothing is copied. The database itself is not touched:
        `FileReference` holds paths relative to the stores, unchanged.
        """
    )

    def add_arguments(self, parser):
        parser.add_argument("db_name", help="Database the existing media belong to.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be done, change nothing.",
        )

    def handle(self, *args, **options):
        db_name = validate_database_name(options["db_name"])
        dry_run = options["dry_run"]
        media_root = os.path.abspath(settings.MEDIA_ROOT)
        tenant_root = os.path.join(media_root, db_name)
        stores = [PublicMediaFileSystemStorage.FILESTORE_DIR] + [
            privacy.lower() for privacy in FileReferencePrivacy.values
        ]

        # Refuse a half-done or repeated move rather than merge two trees.
        to_move = [store for store in stores if os.path.isdir(os.path.join(media_root, store))]
        for store in to_move:
            if os.path.lexists(os.path.join(tenant_root, store)):
                raise CommandError(f"{os.path.join(tenant_root, store)} already exists.")
        if not to_move:
            self.stdout.write("Nothing to move.")

        for store in to_move:
            source, target = os.path.join(media_root, store), os.path.join(tenant_root, store)
            self.stdout.write(f"Move {source} -> {target}")
            if not dry_run:
                os.makedirs(tenant_root, exist_ok=True)
                os.rename(source, target)

        # Symlinks of the media stores, into the filestore.
        old_filestore = os.path.join(media_root, PublicMediaFileSystemStorage.FILESTORE_DIR)
        new_filestore = os.path.join(tenant_root, PublicMediaFileSystemStorage.FILESTORE_DIR)
        rewritten = 0
        for store in stores[1:]:
            # In a dry run nothing moved: look where the links still are.
            store_root = os.path.join(media_root if dry_run and store in to_move else tenant_root, store)
            for directory, dummy, files in os.walk(store_root):
                for file_name in files:
                    link = os.path.join(directory, file_name)
                    if not os.path.islink(link):
                        continue
                    target = os.readlink(link)
                    if not os.path.isabs(target):
                        continue  # already relative: moved along
                    if os.path.commonpath([target, old_filestore]) == old_filestore:
                        target = os.path.join(new_filestore, os.path.relpath(target, old_filestore))
                    final_link = os.path.join(tenant_root, store, os.path.relpath(link, store_root))
                    relative = os.path.relpath(target, os.path.dirname(final_link))
                    rewritten += 1
                    if not dry_run:
                        # Atomic swap: the link is never missing.
                        tmp = f"{link}.tmp-relink"
                        os.symlink(relative, tmp)
                        os.replace(tmp, link)
        self.stdout.write(f"{rewritten} symlink(s) made relative.")
        if dry_run:
            self.stdout.write("Dry run: nothing changed.")
