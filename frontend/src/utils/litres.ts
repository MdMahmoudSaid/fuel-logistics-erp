// Litres are whole numbers in every quantity field: the API sends "45000.00",
// the inputs show and accept "45000".
export function wholeLitres(value: string | number | undefined | null): string {
  const n = Number(value)
  return value === undefined || value === null || value === '' || !Number.isFinite(n)
    ? ''
    : String(Math.round(n))
}

export function isWholeLitres(value: string | number): boolean {
  const n = Number(value)
  return String(value) !== '' && Number.isInteger(n) && n > 0
}
