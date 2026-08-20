import { useI18n } from 'vue-i18n'
import type { TripStatus } from './types'

export function useTripStatusLabel() {
  const { t } = useI18n()
  return (status: TripStatus) => t(`trips.status.${status}`)
}
