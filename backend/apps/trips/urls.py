from rest_framework.routers import DefaultRouter

from .views import TripViewSet

router = DefaultRouter()
router.include_format_suffixes = False
router.register("trips", TripViewSet, basename="trip")

urlpatterns = router.urls
