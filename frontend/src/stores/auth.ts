import { defineStore } from 'pinia'
import axios from 'axios'

interface User {
  id: number
  email: string
  full_name: string
  role: string
}

// Plain axios instance (not api/client.ts) so login/refresh never recurse
// through the 401-refresh interceptor.
const authHttp = axios.create({ baseURL: '/api' })

export const useAuthStore = defineStore('auth', {
  state: () => ({
    accessToken: localStorage.getItem('access_token'),
    refreshToken: localStorage.getItem('refresh_token'),
    user: null as User | null,
  }),

  getters: {
    isAuthenticated: (state) => !!state.accessToken,
  },

  actions: {
    async login(email: string, password: string) {
      const { data } = await authHttp.post('/auth/login/', { email, password })
      this.setTokens(data.access, data.refresh)
      await this.fetchMe()
    },

    async refresh(): Promise<boolean> {
      if (!this.refreshToken) return false
      try {
        const { data } = await authHttp.post('/auth/refresh/', {
          refresh: this.refreshToken,
        })
        this.setTokens(data.access, this.refreshToken)
        return true
      } catch {
        return false
      }
    },

    async fetchMe() {
      const { data } = await authHttp.get('/accounts/users/me/', {
        headers: { Authorization: `Bearer ${this.accessToken}` },
      })
      this.user = data
    },

    setTokens(access: string, refresh: string) {
      this.accessToken = access
      this.refreshToken = refresh
      localStorage.setItem('access_token', access)
      localStorage.setItem('refresh_token', refresh)
    },

    logout() {
      this.accessToken = null
      this.refreshToken = null
      this.user = null
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
    },
  },
})
