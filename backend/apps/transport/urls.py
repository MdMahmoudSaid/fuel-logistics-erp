from rest_framework.routers import DefaultRouter

from .views import DriverViewSet, TransporterViewSet

router = DefaultRouter()
router.register("transporters", TransporterViewSet, basename="transporter")
router.register("drivers", DriverViewSet, basename="driver")

urlpatterns = router.urls
