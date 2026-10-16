import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import BankAccountView from '../BankAccountView.vue'
import CashAccountView from '../CashAccountView.vue'

vi.mock('@/api/resource', () => ({
  createResourceApi: () => ({
    list: vi.fn(async () => ({ count: 0, next: null, previous: null, results: [] })),
  }),
}))

async function openTransfer(component: typeof BankAccountView) {
  const wrapper = mount(component)
  await flushPromises()
  const button = wrapper.findAll('button').find((b) => b.text() === 'Transfert')
  expect(button).toBeTruthy()
  await button!.trigger('click')
  await flushPromises()
  return wrapper
}

describe('Transfert button on the account pages', () => {
  it('opens the transfer form from the bank accounts page, starting from a bank account', async () => {
    const wrapper = await openTransfer(BankAccountView)
    expect((wrapper.find('#source_type').element as HTMLSelectElement).value).toBe('bank')
    expect((wrapper.find('#dest_type').element as HTMLSelectElement).value).toBe('cash')
  })

  it('opens the transfer form from the cash accounts page, starting from a cash account', async () => {
    const wrapper = await openTransfer(CashAccountView)
    expect((wrapper.find('#source_type').element as HTMLSelectElement).value).toBe('cash')
    expect((wrapper.find('#dest_type').element as HTMLSelectElement).value).toBe('bank')
  })
})
