"""The checks every service accepting an uploaded file owes, whatever it stores.

A security floor, not a policy about what a product accepts: each caller keeps
its own narrowing (an allow-list, a smaller size) on top of this.
"""

import mimetypes

from core.services.exceptions import ServiceValidationError

# The handful of types that EXECUTE when served. Uploaded files go out from the
# site's own origin, with no Content-Disposition and no CSP, so an SVG or an
# HTML file there is a stored-XSS vector rather than a document.
EXECUTABLE_MIMETYPES = frozenset(
    {
        "image/svg+xml",
        "text/html",
        "application/xhtml+xml",
        "application/xml",
        "text/xml",
    }
)


def validate_upload(upload, max_size: int, key: str) -> None:
    """Refuse an upload larger than `max_size` bytes, or of an executable type.

    Raises `ServiceValidationError` on `key`, the name of the field carrying
    the upload, so the error lands on that field of the payload.

    Meant for a service's `validate_data`, which runs before the INSERT and so
    before `FileField.pre_save` commits the bytes: a refused upload writes
    nothing, neither a `FileReference` row nor a filestore symlink.

    The size check is NOT belt-and-braces. Nothing else in the stack refuses a
    large upload: nginx allows 300M and answers with an HTML 413 rather than
    JSON, and Django's `DATA_UPLOAD_MAX_MEMORY_SIZE` excludes file fields by
    design.
    """
    if upload.size > max_size:
        raise ServiceValidationError(
            f"The file is too large ({upload.size} bytes). "
            f"The maximum is {max_size} bytes.",
            key=key,
        )

    # Guessed from the FILENAME, deliberately, and not read from
    # `upload.content_type`: the filename guess is what the services store in
    # their `mimetype` column, so checking anything else would let the stored
    # value disagree with what was accepted. The declared content type is also
    # the field a caller fully controls.
    mimetype = mimetypes.guess_type(upload.name or "")[0]
    if mimetype in EXECUTABLE_MIMETYPES:
        raise ServiceValidationError(
            f"A {mimetype} file cannot be uploaded: it would execute script "
            f"when served from the site's own domain.",
            key=key,
        )
