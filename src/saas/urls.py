from django.urls import path

from saas.api import saas_api

urlpatterns = [
    path("saas/", saas_api.urls),
]
