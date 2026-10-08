/** Keep authoritative decimal strings exact; never round through binary Number. */
export function unitPrice(value) {
  if (typeof value !== 'string' || !/^(0|[1-9][0-9]{0,11})\.[0-9]{4}$/.test(value)) return 'Price on request'
  const [whole, fractional] = value.split('.')
  let decimals = fractional
  while (decimals.length > 2 && decimals.endsWith('0')) decimals = decimals.slice(0, -1)
  return `USD ${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}.${decimals}`
}

export function money(value) {
  if (typeof value !== 'string' || !/^(0|[1-9][0-9]{0,17})\.[0-9]{2}$/.test(value)) return 'To be confirmed'
  const [whole, fraction] = value.split('.')
  return `USD ${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}.${fraction}`
}

export function beijingTime(value) {
  if (typeof value !== 'string') return 'unavailable'
  const instant = Date.parse(/(Z|[+-]\d{2}:\d{2})$/.test(value) ? value : value + '+08:00')
  if (!Number.isFinite(instant)) return 'unavailable'
  return new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Shanghai', day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(instant) + ' (Beijing)'
}
