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
          component: () => import('@/modules/dashboard/DashboardView.vue'),
        },
        {
          path: 'reports',
          name: 'reports',
          component: () => import('@/modules/reports/ReportsView.vue'),
        },
        {
          path: 'loss-report',
          name: 'loss-report',
          component: () => import('@/modules/reports/ReportsView.vue'),
        },
        {
          path: 'audit-logs',
          name: 'audit-logs',
          component: () => import('@/modules/audit/AuditLogViewer.vue'),
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
          path: 'company-stock',
          name: 'company-stock',
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
        // Documents section (spec 2026-10-11 documents-commerciaux §1): one
        // generic list per kind; the proforma keeps the quotation form.
        { path: 'quotations', redirect: { name: 'proformas' } },
        { path: 'quotations/:id', redirect: (to) => `/documents/proformas/${to.params.id}` },
        {
          path: 'documents/proformas',
          name: 'proformas',
          component: () => import('@/modules/documents/DocumentList.vue'),
          props: { kind: 'proforma' },
        },
        {
          path: 'documents/proformas/new',
          name: 'quotation-new',
          component: () => import('@/modules/quotations/QuotationForm.vue'),
        },
        {
          path: 'documents/proformas/:id',
          name: 'quotation-detail',
          component: () => import('@/modules/quotations/QuotationForm.vue'),
        },
        {
          path: 'documents/delivery-notes',
          name: 'delivery-notes',
          component: () => import('@/modules/documents/DocumentList.vue'),
          props: { kind: 'delivery' },
        },
        {
          path: 'documents/delivery-notes/new',
          name: 'delivery-note-new',
          component: () => import('@/modules/documents/DeliveryNoteForm.vue'),
        },
        {
          path: 'documents/delivery-notes/:id',
          name: 'delivery-note-detail',
          component: () => import('@/modules/documents/DeliveryNoteForm.vue'),
        },
        {
          path: 'documents/loading-sheets',
          name: 'loading-sheets',
          component: () => import('@/modules/documents/DocumentList.vue'),
          props: { kind: 'loading' },
        },
        {
          path: 'documents/loading-sheets/new',
          name: 'loading-sheet-new',
          component: () => import('@/modules/documents/LoadingSheetForm.vue'),
        },
        {
          path: 'documents/loading-sheets/:id',
          name: 'loading-sheet-detail',
          component: () => import('@/modules/documents/LoadingSheetForm.vue'),
        },
        {
          path: 'documents/purchase-orders',
          name: 'purchase-orders',
          component: () => import('@/modules/documents/DocumentList.vue'),
          props: { kind: 'purchase' },
        },
        {
          path: 'documents/purchase-orders/new',
          name: 'purchase-order-doc-new',
          component: () => import('@/modules/documents/PurchaseOrderForm.vue'),
        },
        {
          path: 'documents/purchase-orders/:id',
          name: 'purchase-order-doc-detail',
          component: () => import('@/modules/documents/PurchaseOrderForm.vue'),
        },
        {
          path: 'settings/company',
          name: 'company-settings',
          component: () => import('@/modules/settings/CompanyProfileSettings.vue'),
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
          // "Enregistrer un paiement client" est désormais une modale ouverte
          // depuis Factures/Clients — cette route ne sert plus qu'à la
          // rétrocompatibilité des anciens liens.
          path: 'customer-payments/new',
          redirect: (to) => ({
            name: 'invoices',
            query: {
              action: 'payment',
              ...(to.query.customer ? { customer: to.query.customer } : {}),
            },
          }),
        },
        {
          // "Enregistrer une dépense" est désormais une modale ouverte depuis
          // le Journal de trésorerie — rétrocompatibilité des anciens liens.
          path: 'expenses/new',
          redirect: { name: 'treasury-transactions', query: { action: 'expense' } },
        },
        {
          path: 'treasury/transactions',
          name: 'treasury-transactions',
          component: () => import('@/modules/finance/TreasuryLedgerView.vue'),
        },
        {
          path: 'expenses',
          name: 'expenses',
          component: () => import('@/modules/finance/ExpensesView.vue'),
        },
        {
          // "Transfert interne" est désormais une modale ouverte depuis le
          // Journal de trésorerie — rétrocompatibilité des anciens liens.
          path: 'treasury/transfer',
          redirect: { name: 'treasury-transactions', query: { action: 'transfer' } },
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
        {
          path: 'shareholders',
          name: 'shareholders',
          component: () => import('@/modules/finance/ShareholderView.vue'),
        },
        {
          path: 'profit',
          name: 'profit',
          component: () => import('@/modules/finance/ProfitView.vue'),
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
