import type { TruckBrief } from './types'

export function formatTruckPlates(truck: TruckBrief | null | undefined): string {
  if (!truck) return '—'
  const tractor = truck.tractor_registration || '—'
  const tanker = truck.tanker_registration || '—'
  return `${tractor} / ${tanker}`
}
