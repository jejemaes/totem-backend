from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from ninja import NinjaAPI, Redoc

api_v1 = NinjaAPI(
    version='1',
    docs=Redoc(),
    title="Totem API",
    description="This is the OpenAPI Documentation for Totem API v1."
)


@api_v1.exception_handler(ObjectDoesNotExist)
def handle_object_does_not_exist(request, exc):
    return api_v1.create_response(
        request,
        {"detail": "Object not found"},
        status=404,
    )


@api_v1.exception_handler(ValidationError)
def handle_validation_error(request, exc):
    return api_v1.create_response(
        request,
        {"detail": exc.messages},
        status=400,
    )


@api_v1.exception_handler(PermissionDenied)
def handle_permission_denied(request, exc):
    return api_v1.create_response(
        request,
        {"detail": [str(exc)]},
        status=403,
    )
