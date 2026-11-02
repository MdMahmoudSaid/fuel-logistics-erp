import { describe, it, expect, vi, beforeEach } from 'vitest'

const post = vi.fn(async (_url: string, _payload: unknown) => ({ data: [] }))
vi.mock('@/api/client', () => ({
  apiClient: { post: (url: string, payload: unknown) => post(url, payload), get: vi.fn() },
}))

import { postDirectSale, confirmReceivedQuantity } from '../api'

describe('direct sale api', () => {
  beforeEach(() => vi.clearAllMocks())

  it('postDirectSale POSTs the payload to /trips/direct-sale/', async () => {
    const payload = { trips: [1, 2], walk_in_name: 'Moussa', unit_selling_price: '800.0000' }
    await postDirectSale(payload)
    expect(post).toHaveBeenCalledWith('/trips/direct-sale/', payload)
  })

  it('confirmReceivedQuantity POSTs to the trip confirm-received-quantity route', async () => {
    const payload = { received_quantity: '44000.00' }
    await confirmReceivedQuantity(7, payload)
    expect(post).toHaveBeenCalledWith('/trips/7/confirm-received-quantity/', payload)
  })
})
