import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useAuthStore } from '@/stores/auth'

describe('auth store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('starts unauthenticated with no stored tokens', () => {
    const auth = useAuthStore()
    expect(auth.isAuthenticated).toBe(false)
  })

  it('setTokens persists tokens and flips isAuthenticated', () => {
    const auth = useAuthStore()
    auth.setTokens('access-123', 'refresh-456')

    expect(auth.isAuthenticated).toBe(true)
    expect(localStorage.getItem('access_token')).toBe('access-123')
    expect(localStorage.getItem('refresh_token')).toBe('refresh-456')
  })

  it('logout clears tokens and user', () => {
    const auth = useAuthStore()
    auth.setTokens('access-123', 'refresh-456')

    auth.logout()

    expect(auth.isAuthenticated).toBe(false)
    expect(auth.user).toBeNull()
    expect(localStorage.getItem('access_token')).toBeNull()
  })

  it('can() reflects the role permission matrix', () => {
    const auth = useAuthStore()
    auth.user = {
      id: 1,
      email: 'ops@example.com',
      full_name: '',
      role: 3,
      role_detail: { id: 3, name: 'Operations', permissions: { operations: ['view', 'create'] } },
    }

    expect(auth.can('operations', 'create')).toBe(true)
    expect(auth.can('finance', 'view')).toBe(false)
  })

  it('can() returns false when there is no authenticated user', () => {
    const auth = useAuthStore()
    expect(auth.can('operations', 'view')).toBe(false)
  })
})
