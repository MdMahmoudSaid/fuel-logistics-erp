from rest_framework.routers import DefaultRouter

from .views import (
    BankAccountViewSet,
    CashAccountViewSet,
    CustomerPaymentViewSet,
    ExpenseViewSet,
    SupplierPaymentViewSet,
    TransporterAdvanceViewSet,
    TransportPaymentViewSet,
    TreasuryTransactionViewSet,
)

router = DefaultRouter()
router.register("bank-accounts", BankAccountViewSet, basename="bankaccount")
router.register("cash-accounts", CashAccountViewSet, basename="cashaccount")
router.register("customer-payments", CustomerPaymentViewSet, basename="customerpayment")
router.register("supplier-payments", SupplierPaymentViewSet, basename="supplierpayment")
router.register("transporter-advances", TransporterAdvanceViewSet, basename="transporteradvance")
router.register("transport-payments", TransportPaymentViewSet, basename="transportpayment")
router.register("expenses", ExpenseViewSet, basename="expense")
router.register("treasury-transactions", TreasuryTransactionViewSet, basename="treasurytransaction")

urlpatterns = router.urls
