import { ref } from 'vue'
import { createResourceApi } from '@/api/resource'

export interface RoleRecord {
  id: number
  name: string
  permissions: Record<string, string[]>
}

const resource = createResourceApi<RoleRecord>('/accounts/roles/')
const roles = ref<RoleRecord[]>([])
let loaded = false

export async function loadRoles() {
  if (!loaded) {
    const data = await resource.list()
    roles.value = data.results
    loaded = true
  }
  return roles.value
}

export function useRoles() {
  return { roles }
}
