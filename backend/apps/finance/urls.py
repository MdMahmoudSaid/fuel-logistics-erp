from rest_framework.routers import DefaultRouter

from .views import BankAccountViewSet, CashAccountViewSet

router = DefaultRouter()
router.register("bank-accounts", BankAccountViewSet, basename="bankaccount")
router.register("cash-accounts", CashAccountViewSet, basename="cashaccount")

urlpatterns = router.urls
