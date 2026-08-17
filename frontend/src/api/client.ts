import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { useAuthStore } from '@/stores/auth'

export const apiClient = axios.create({
  baseURL: '/api',
  timeout: 15000,
})

apiClient.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.accessToken) {
    config.headers.Authorization = `Bearer ${auth.accessToken}`
  }
  return config
})

// Weak-internet support (spec §41): retry idempotent GET requests once on
// network failure before surfacing the error to the caller.
apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as (InternalAxiosRequestConfig & { _retried?: boolean }) | undefined

    if (error.response?.status === 401) {
      const auth = useAuthStore()
      const refreshed = await auth.refresh()
      if (refreshed && config) {
        config.headers.Authorization = `Bearer ${auth.accessToken}`
        return apiClient(config)
      }
      auth.logout()
    }

    const isNetworkError = !error.response
    if (isNetworkError && config?.method === 'get' && !config._retried) {
      config._retried = true
      return apiClient(config)
    }

    return Promise.reject(error)
  },
)
