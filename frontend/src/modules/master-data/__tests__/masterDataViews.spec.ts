import { describe, it, expect } from 'vitest'
import { shallowMount } from '@vue/test-utils'
import MasterDataView from '@/components/master-data/MasterDataView.vue'
import ProductView from '@/modules/products/ProductView.vue'
import SupplierView from '@/modules/suppliers/SupplierView.vue'
import CustomerView from '@/modules/customers/CustomerView.vue'
import TransporterView from '@/modules/transporters/TransporterView.vue'
import DriverView from '@/modules/drivers/DriverView.vue'
import TruckView from '@/modules/trucks/TruckView.vue'
import BankAccountView from '@/modules/finance/BankAccountView.vue'
import CashAccountView from '@/modules/finance/CashAccountView.vue'
import UserView from '@/modules/users/UserView.vue'
import { i18n } from '@/i18n'

const views = [
  ['ProductView', ProductView, 'Produits'],
  ['SupplierView', SupplierView, 'Fournisseurs'],
  ['CustomerView', CustomerView, 'Clients'],
  ['TransporterView', TransporterView, 'Transporteurs'],
  ['DriverView', DriverView, 'Chauffeurs'],
  ['TruckView', TruckView, 'Camions'],
  ['BankAccountView', BankAccountView, 'Comptes bancaires'],
  ['CashAccountView', CashAccountView, 'Comptes de caisse'],
  ['UserView', UserView, 'Utilisateurs'],
] as const

describe('master-data thin wrapper views', () => {
  it.each(views)(
    '%s renders MasterDataView with the right title and a non-empty field schema',
    (_name, component, expectedTitle) => {
      const wrapper = shallowMount(component, {
        global: { stubs: { MasterDataView: true }, plugins: [i18n] },
      })
      const masterDataView = wrapper.findComponent(MasterDataView)

      expect(masterDataView.props('title')).toBe(expectedTitle)
      expect((masterDataView.props('fields') as unknown[]).length).toBeGreaterThan(0)
      expect(masterDataView.props('resource')).toBeDefined()
    },
  )
})
