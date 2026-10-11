from rest_framework.routers import DefaultRouter

from .views import DeliveryNoteViewSet, LoadingSheetViewSet, PurchaseOrderDocumentViewSet

router = DefaultRouter()
router.include_format_suffixes = False
router.register("delivery-notes", DeliveryNoteViewSet, basename="delivery-note")
router.register("loading-sheets", LoadingSheetViewSet, basename="loading-sheet")
router.register("purchase-order-documents", PurchaseOrderDocumentViewSet, basename="purchase-order-document")

urlpatterns = router.urls
