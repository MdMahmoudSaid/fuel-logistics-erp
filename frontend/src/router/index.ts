import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/modules/auth/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/',
      component: () => import('@/modules/shell/AppShell.vue'),
      children: [
        {
          path: '',
          name: 'home',
          component: () => import('@/modules/shell/DashboardPlaceholder.vue'),
        },
        {
          path: 'products',
          name: 'products',
          component: () => import('@/modules/products/ProductView.vue'),
        },
        {
          path: 'suppliers',
          name: 'suppliers',
          component: () => import('@/modules/suppliers/SupplierView.vue'),
        },
        {
          path: 'suppliers/:id/ledger',
          name: 'supplier-ledger',
          component: () => import('@/modules/suppliers/SupplierLedgerView.vue'),
        },
        {
          path: 'supplier-orders',
          name: 'supplier-orders',
          component: () => import('@/modules/purchasing/SupplierOrderList.vue'),
        },
        {
          path: 'supplier-orders/new',
          name: 'supplier-order-new',
          component: () => import('@/modules/purchasing/SupplierOrderForm.vue'),
        },
        {
          path: 'supplier-orders/:id',
          name: 'supplier-order-detail',
          component: () => import('@/modules/purchasing/SupplierOrderForm.vue'),
        },
        {
          path: 'cession-letters',
          name: 'cession-letters',
          component: () => import('@/modules/purchasing/CessionLetterList.vue'),
        },
        {
          path: 'cession-letters/new',
          name: 'cession-letter-new',
          component: () => import('@/modules/purchasing/CessionLetterForm.vue'),
        },
        {
          path: 'cession-letters/:id',
          name: 'cession-letter-detail',
          component: () => import('@/modules/purchasing/CessionLetterForm.vue'),
        },
        {
          path: 'customer-orders',
          name: 'customer-orders',
          component: () => import('@/modules/sales/CustomerOrderList.vue'),
        },
        {
          path: 'customer-orders/new',
          name: 'customer-order-new',
          component: () => import('@/modules/sales/CustomerOrderForm.vue'),
        },
        {
          path: 'customer-orders/:id',
          name: 'customer-order-detail',
          component: () => import('@/modules/sales/CustomerOrderForm.vue'),
        },
        {
          path: 'trips',
          name: 'trips',
          component: () => import('@/modules/trips/TripStatusBoard.vue'),
        },
        {
          path: 'trips/new',
          name: 'trip-new',
          component: () => import('@/modules/trips/TripForm.vue'),
        },
        {
          path: 'trips/:id',
          name: 'trip-detail',
          component: () => import('@/modules/trips/TripDetail.vue'),
        },
        {
          path: 'sales',
          name: 'sales',
          component: () => import('@/modules/sales/SaleList.vue'),
        },
        {
          path: 'invoices',
          name: 'invoices',
          component: () => import('@/modules/sales/InvoiceList.vue'),
        },
        {
          path: 'invoices/:id',
          name: 'invoice-detail',
          component: () => import('@/modules/sales/InvoiceDetail.vue'),
        },
        {
          path: 'settings/loss-tolerance',
          name: 'loss-tolerance-settings',
          component: () => import('@/modules/settings/LossToleranceSettings.vue'),
        },
        {
          path: 'customers',
          name: 'customers',
          component: () => import('@/modules/customers/CustomerView.vue'),
        },
        {
          path: 'customers/:id/ledger',
          name: 'customer-ledger',
          component: () => import('@/modules/finance/CustomerLedgerView.vue'),
        },
        {
          path: 'customer-payments/new',
          name: 'customer-payment-new',
          component: () => import('@/modules/finance/PaymentAllocationForm.vue'),
        },
        {
          path: 'expenses/new',
          name: 'expense-new',
          component: () => import('@/modules/finance/ExpenseForm.vue'),
        },
        {
          path: 'treasury/transactions',
          name: 'treasury-transactions',
          component: () => import('@/modules/finance/TreasuryLedgerView.vue'),
        },
        {
          path: 'treasury/transfer',
          name: 'treasury-transfer',
          component: () => import('@/modules/finance/TransferForm.vue'),
        },
        {
          path: 'transporters',
          name: 'transporters',
          component: () => import('@/modules/transporters/TransporterView.vue'),
        },
        {
          path: 'transporters/:id/ledger',
          name: 'transporter-ledger',
          component: () => import('@/modules/finance/TransporterLedgerView.vue'),
        },
        {
          path: 'drivers',
          name: 'drivers',
          component: () => import('@/modules/drivers/DriverView.vue'),
        },
        {
          path: 'trucks',
          name: 'trucks',
          component: () => import('@/modules/trucks/TruckView.vue'),
        },
        {
          path: 'bank-accounts',
          name: 'bank-accounts',
          component: () => import('@/modules/finance/BankAccountView.vue'),
        },
        {
          path: 'cash-accounts',
          name: 'cash-accounts',
          component: () => import('@/modules/finance/CashAccountView.vue'),
        },
        { path: 'users', name: 'users', component: () => import('@/modules/users/UserView.vue') },
        {
          path: 'roles',
          name: 'roles',
          component: () => import('@/modules/roles/RoleListView.vue'),
        },
      ],
    },
  ],
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.isAuthenticated) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && auth.isAuthenticated) {
    return { name: 'home' }
  }
  return true
})

export default router
