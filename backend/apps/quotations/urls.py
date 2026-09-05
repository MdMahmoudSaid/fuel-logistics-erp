from rest_framework.routers import DefaultRouter

from .views import QuotationViewSet

router = DefaultRouter()
router.include_format_suffixes = False
router.register("quotations", QuotationViewSet, basename="quotation")

urlpatterns = router.urls
