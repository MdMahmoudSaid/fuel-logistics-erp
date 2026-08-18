from rest_framework.routers import DefaultRouter
from django.urls import path, include
from .views import DocumentViewSet

router = DefaultRouter()
router.register("documents", DocumentViewSet, basename="document")

urlpatterns = [
    path("", include(router.urls)),
]
