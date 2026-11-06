function cents(value) {
  if (!['number', 'string'].includes(typeof value) || String(value).trim() === '') return null
  const number = Number(value)
  if (!Number.isFinite(number)) return null
  // Decimal shifting avoids 1.005 * 100 falling just below the half-cent.
  const [coefficient, exponent = '0'] = String(number).split('e')
  const shifted = Number(`${coefficient}e${Number(exponent) + 2}`)
  const result = Math.sign(shifted) * Math.round(Math.abs(shifted))
  return Number.isSafeInteger(result) ? result : null
}

export function receivedAmountTone(received, payable) {
  const receivedCents = cents(received)
  const payableCents = cents(payable)
  if (receivedCents === null || payableCents === null) return 'unknown'
  if (receivedCents === payableCents) return 'equal'
  return receivedCents > payableCents ? 'overpaid' : 'underpaid'
}
