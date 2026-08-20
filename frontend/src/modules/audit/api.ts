import { createResourceApi } from '@/api/resource'
import type { AuditLog } from './types'

export const auditLogResource = createResourceApi<AuditLog>('/audit-logs/')
