import type { AccountStatus } from './types'

export interface StatusAction {
  label: string
  target: AccountStatus
  tone: string
}

// Row actions that move a record between Actifs / Anciens / Inactifs.
// `t` is the i18n translate function.
export function buildStatusActions(
  row: { is_active?: unknown; is_legacy?: unknown },
  legacySupport: boolean | undefined,
  t: (key: string) => string,
): StatusAction[] {
  if (row.is_legacy) {
    return [
      { label: t('masterData.reactivate'), target: 'active', tone: 'text-livre' },
      { label: t('masterData.deactivate'), target: 'inactive', tone: 'text-critique' },
    ]
  }
  if (row.is_active) {
    const actions: StatusAction[] = []
    if (legacySupport)
      actions.push({ label: t('masterData.markLegacy'), target: 'legacy', tone: 'text-ecart' })
    actions.push({ label: t('masterData.deactivate'), target: 'inactive', tone: 'text-critique' })
    return actions
  }
  return [{ label: t('masterData.activate'), target: 'active', tone: 'text-livre' }]
}

// PATCH body for moving a record to `status`.
export function statusPayload(
  status: AccountStatus,
  legacySupport: boolean | undefined,
): Record<string, unknown> {
  if (status === 'legacy') return { is_legacy: true, is_active: false }
  if (status === 'active')
    return { is_active: true, ...(legacySupport ? { is_legacy: false } : {}) }
  return { is_active: false }
}
