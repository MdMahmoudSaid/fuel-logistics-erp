from rest_framework.routers import DefaultRouter

from .views import (
    AllocatableTypesViewSet,
    BankAccountViewSet,
    CashAccountViewSet,
    CustomerPaymentViewSet,
    ExpenseViewSet,
    ShareholderLoanViewSet,
    ShareholderProfitDistributionViewSet,
    ShareholderViewSet,
    ShareholderWithdrawalViewSet,
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
router.register("allocatable-types", AllocatableTypesViewSet, basename="allocatabletype")
router.register("shareholders", ShareholderViewSet, basename="shareholder")
router.register(
    "shareholder-distributions", ShareholderProfitDistributionViewSet, basename="shareholderdistribution"
)
router.register("shareholder-loans", ShareholderLoanViewSet, basename="shareholderloan")
router.register("shareholder-withdrawals", ShareholderWithdrawalViewSet, basename="shareholderwithdrawal")

urlpatterns = router.urls
