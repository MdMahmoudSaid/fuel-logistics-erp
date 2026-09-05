// Pure aggregation helpers over LossReportQuery rows (backend/apps/reports/
// queries/loss_report.py), reused for the "Volume livré du jour", "Écart
// moyen %", "À traiter" and 14-day chart pieces of the Étape 6 dashboard.
// Kept dependency-free from the API layer so it's cheap to unit test.

export interface LossReportRow {
  trip_reference: string
  control_date: string
  loaded_quantity: string
  received_quantity: string
  loss_quantity: string
  tolerance_quantity: string
  chargeable_loss_quantity: string
  // Recette corrections (2026-09-05): lets TripDetail.vue tell whether a
  // client verification was already recorded on this trip (verified_at set)
  // - null/absent means "not yet verified".
  verified_at?: string | null
  notes?: string
}

export function sumField(
  rows: LossReportRow[],
  field: 'loaded_quantity' | 'received_quantity',
): number {
  return rows.reduce((total, row) => total + Number(row[field]), 0)
}

// Average of (loss / loaded) per delivery control, not (total loss / total
// loaded) — each control weighs equally regardless of trip size, which
// better answers "how off is a typical delivery" than a volume-weighted mean.
export function averageLossPercent(rows: LossReportRow[]): number {
  const withLoaded = rows.filter((row) => Number(row.loaded_quantity) > 0)
  if (!withLoaded.length) return 0
  const total = withLoaded.reduce(
    (sum, row) => sum + (Number(row.loss_quantity) / Number(row.loaded_quantity)) * 100,
    0,
  )
  return total / withLoaded.length
}

// Seuils de sévérité partagés entre le Dashboard (écart moyen du jour) et
// le bloc Jauges de TripDetail (écart d'un trajet donné) - au-delà de 2%
// c'est critique, au-delà de 0.5% ça mérite un oeil, en-dessous c'est sain.
export function lossSeverityTone(pct: number): 'livre' | 'ecart' | 'critique' {
  if (pct > 2) return 'critique'
  if (pct > 0.5) return 'ecart'
  return 'livre'
}

// "Écart non justifié" = perte au-delà de la tolérance (chargeable), donc
// pas absorbée automatiquement — à traiter par les opérations.
export function unjustifiedLosses(rows: LossReportRow[]): LossReportRow[] {
  return rows
    .filter((row) => Number(row.chargeable_loss_quantity) > 0)
    .sort((a, b) => Number(b.chargeable_loss_quantity) - Number(a.chargeable_loss_quantity))
}

export interface VolumeDay {
  date: string
  dayLabel: string
  value: number
  isToday: boolean
}

const DAY_LABELS = ['Dim', 'Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam']

function toIsoDate(d: Date): string {
  return d.toISOString().slice(0, 10)
}

// Last `n` calendar days ending today (inclusive), oldest first.
export function lastNDays(n: number, today = new Date()): VolumeDay[] {
  const days: VolumeDay[] = []
  for (let i = n - 1; i >= 0; i--) {
    const d = new Date(today)
    d.setDate(d.getDate() - i)
    days.push({
      date: toIsoDate(d),
      dayLabel: DAY_LABELS[d.getDay()] ?? '',
      value: 0,
      isToday: i === 0,
    })
  }
  return days
}

export function groupVolumeByDay(rows: LossReportRow[], days: VolumeDay[]): VolumeDay[] {
  const totals = new Map<string, number>()
  for (const row of rows) {
    totals.set(
      row.control_date,
      (totals.get(row.control_date) ?? 0) + Number(row.received_quantity),
    )
  }
  return days.map((day) => ({ ...day, value: totals.get(day.date) ?? 0 }))
}
