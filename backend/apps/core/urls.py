from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import LossToleranceConfigView, ProductViewSet

router = DefaultRouter()
router.include_format_suffixes = False
router.register("products", ProductViewSet, basename="product")

urlpatterns = router.urls + [
    path(
        "settings/loss-tolerance/",
        LossToleranceConfigView.as_view(),
        name="loss-tolerance-config",
    ),
]
