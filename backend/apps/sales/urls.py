from rest_framework.routers import DefaultRouter

from .views import CustomerOrderViewSet

router = DefaultRouter()
router.register("customer-orders", CustomerOrderViewSet, basename="customer-order")

urlpatterns = router.urls
