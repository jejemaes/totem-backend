import os
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404, HttpResponse
from django.views.generic.base import View

from base.choices import FileReferencePrivacy
from base.files.storages import PublicMediaFileSystemStorage, private_media_salt
from base.models import FileReference
from core.db.tenancy import current_database
from core.utils import signing

# Served by nginx only as the target of an `X-Accel-Redirect` (`internal`).
INTERNAL_MEDIA_URL = "/_media_internal/"


class ServeSignedUrlsStorageNginxView(View):

    def dispatch(self, request, path, *args, **kwargs):
        is_ok = signing.check_signature(request.get_full_path(), salt=private_media_salt())
        if not is_ok:
            raise PermissionDenied()
        return super().dispatch(request, path=path, *args, **kwargs)

    def get(self, request, path, *args, **kwargs):
        full_path = request.get_full_path()
        url_parsed = urlparse(full_path)

        file_path = url_parsed.path.replace(f"{settings.MEDIA_URL.rstrip('/')}/{FileReferencePrivacy.PRIVATE}/", '')
        try:
            file_reference = FileReference.objects.get(privacy=FileReferencePrivacy.PRIVATE, symbolic_path=file_path)
            # Internal location of nginx, mapped on `MEDIA_ROOT`. The database
            # is named by Django rather than taken from the header by nginx:
            # the file belongs to the database the reference was read from.
            x_redirect = os.path.join(
                INTERNAL_MEDIA_URL,
                current_database(),
                PublicMediaFileSystemStorage.FILESTORE_DIR,
                file_reference.store_path.lstrip("/"),
            )
            mimetype = file_reference.mimetype
        except ObjectDoesNotExist:
            raise Http404

        resp = HttpResponse()
        resp['X-Accel-Redirect'] = x_redirect
        resp['Content-Type'] = mimetype
        return resp
