from rest_framework.routers import DefaultRouter

from .views import SupplierViewSet

router = DefaultRouter()
router.include_format_suffixes = False
router.register("suppliers", SupplierViewSet, basename="supplier")

urlpatterns = router.urls
