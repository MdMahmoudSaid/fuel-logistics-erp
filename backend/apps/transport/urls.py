from rest_framework.routers import DefaultRouter

from .views import DriverViewSet, TransporterViewSet, TruckViewSet

router = DefaultRouter()
router.register("transporters", TransporterViewSet, basename="transporter")
router.register("drivers", DriverViewSet, basename="driver")
router.register("trucks", TruckViewSet, basename="truck")

urlpatterns = router.urls
