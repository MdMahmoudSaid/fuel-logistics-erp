from rest_framework.routers import DefaultRouter

from .views import (
    AllocatableTypesViewSet,
    BankAccountViewSet,
    CashAccountViewSet,
    CustomerPaymentViewSet,
    ExpenseCategoryViewSet,
    ExpenseViewSet,
    ShareholderContributionViewSet,
    ShareholderLoanViewSet,
    ShareholderProfitDistributionViewSet,
    ShareholderProfitPeriodViewSet,
    ShareholderViewSet,
    ShareholderWithdrawalViewSet,
    SupplierAdvanceViewSet,
    SupplierPaymentViewSet,
    TransporterAdvanceViewSet,
    TransportPaymentViewSet,
    TreasuryTransactionViewSet,
)

router = DefaultRouter()
router.include_format_suffixes = False
router.register("bank-accounts", BankAccountViewSet, basename="bankaccount")
router.register("cash-accounts", CashAccountViewSet, basename="cashaccount")
router.register("customer-payments", CustomerPaymentViewSet, basename="customerpayment")
router.register("supplier-payments", SupplierPaymentViewSet, basename="supplierpayment")
router.register("supplier-advances", SupplierAdvanceViewSet, basename="supplieradvance")
router.register("transporter-advances", TransporterAdvanceViewSet, basename="transporteradvance")
router.register("transport-payments", TransportPaymentViewSet, basename="transportpayment")
router.register("expenses", ExpenseViewSet, basename="expense")
router.register("expense-categories", ExpenseCategoryViewSet, basename="expensecategory")
router.register("treasury-transactions", TreasuryTransactionViewSet, basename="treasurytransaction")
router.register("allocatable-types", AllocatableTypesViewSet, basename="allocatabletype")
router.register("shareholders", ShareholderViewSet, basename="shareholder")
router.register(
    "shareholder-distributions", ShareholderProfitDistributionViewSet, basename="shareholderdistribution"
)
router.register("shareholder-periods", ShareholderProfitPeriodViewSet, basename="shareholderprofitperiod")
router.register("shareholder-loans", ShareholderLoanViewSet, basename="shareholderloan")
router.register("shareholder-withdrawals", ShareholderWithdrawalViewSet, basename="shareholderwithdrawal")
router.register(
    "shareholder-contributions", ShareholderContributionViewSet, basename="shareholdercontribution"
)

urlpatterns = router.urls
