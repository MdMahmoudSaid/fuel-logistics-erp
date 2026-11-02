import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import TripCard from '../TripCard.vue'
import type { Trip } from '../types'

function mountCard(overrides: Partial<Trip>) {
  const router = createRouter({
    history: createWebHistory(),
    routes: [{ path: '/trips/:id', name: 'trip-detail', component: { template: '<div />' } }],
  })
  const trip = {
    id: 1,
    reference: 'TRIP-001',
    truck_detail: null,
    destination_type: 'CUSTOMER',
    client_detail: { id: 2, name: 'Client A' },
    cession_letter_detail: null,
    product_detail: null,
    quantity_loaded: '45000.00',
    status: 'ARRIVED_AT_CLIENT',
    ...overrides,
  } as unknown as Trip
  return mount(TripCard, { props: { trip }, global: { plugins: [router] } })
}

describe('TripCard', () => {
  it('flags a trip attributed with a parked price as awaiting its received quantity', () => {
    const wrapper = mountCard({ pending_unit_selling_price: '900.0000' })
    expect(wrapper.find('[data-test="awaiting-quantity"]').exists()).toBe(true)
  })

  it('shows no such flag without a parked price', () => {
    const wrapper = mountCard({ pending_unit_selling_price: null })
    expect(wrapper.find('[data-test="awaiting-quantity"]').exists()).toBe(false)
  })
})
