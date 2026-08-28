from rest_framework.routers import DefaultRouter
from django.urls import path, include
from .views import SupplierOrderViewSet, CessionLetterViewSet

router = DefaultRouter()
router.include_format_suffixes = False
router.register("supplier-orders", SupplierOrderViewSet, basename="supplier-order")
router.register("cession-letters", CessionLetterViewSet, basename="cession-letter")

urlpatterns = [
    path("", include(router.urls)),
]
