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

const views = [
  ['ProductView', ProductView, 'Products'],
  ['SupplierView', SupplierView, 'Suppliers'],
  ['CustomerView', CustomerView, 'Customers'],
  ['TransporterView', TransporterView, 'Transporters'],
  ['DriverView', DriverView, 'Drivers'],
  ['TruckView', TruckView, 'Trucks'],
  ['BankAccountView', BankAccountView, 'Bank Accounts'],
  ['CashAccountView', CashAccountView, 'Cash Accounts'],
  ['UserView', UserView, 'Users'],
] as const

describe('master-data thin wrapper views', () => {
  it.each(views)(
    '%s renders MasterDataView with the right title and a non-empty field schema',
    (_name, component, expectedTitle) => {
      const wrapper = shallowMount(component, { global: { stubs: { MasterDataView: true } } })
      const masterDataView = wrapper.findComponent(MasterDataView)

      expect(masterDataView.props('title')).toBe(expectedTitle)
      expect((masterDataView.props('fields') as unknown[]).length).toBeGreaterThan(0)
      expect(masterDataView.props('resource')).toBeDefined()
    },
  )
})
