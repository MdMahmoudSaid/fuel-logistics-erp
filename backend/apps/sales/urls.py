from rest_framework.routers import DefaultRouter

from .views import CustomerOrderViewSet, InvoiceViewSet, SaleViewSet

router = DefaultRouter()
router.include_format_suffixes = False
router.register("customer-orders", CustomerOrderViewSet, basename="customer-order")
router.register("sales", SaleViewSet, basename="sale")
router.register("invoices", InvoiceViewSet, basename="invoice")

urlpatterns = router.urls
