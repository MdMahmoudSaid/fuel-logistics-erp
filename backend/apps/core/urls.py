from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import CompanyProfileView, LossToleranceConfigView, ProductViewSet

router = DefaultRouter()
router.include_format_suffixes = False
router.register("products", ProductViewSet, basename="product")

urlpatterns = router.urls + [
    path(
        "settings/loss-tolerance/",
        LossToleranceConfigView.as_view(),
        name="loss-tolerance-config",
    ),
    path("settings/company/", CompanyProfileView.as_view(), name="company-profile"),
]
