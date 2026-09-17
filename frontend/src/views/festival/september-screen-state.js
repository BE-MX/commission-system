import { parseApiDateTime } from '../../utils/datetime.js'

const finite = value => typeof value === 'number' && Number.isFinite(value) && value >= 0
const integer = value => finite(value) && Number.isInteger(value)

/** Do not replace a good screen snapshot with a malformed/partial response. */
export function validPayload(data) {
  if (!data || !Array.isArray(data.groups) || data.groups.length !== 8) return false
  if (!parseApiDateTime(data.as_of) || data.period?.start !== '2026-09-01' || data.period?.end !== '2026-09-30') return false
  if (!['upcoming', 'ongoing', 'pending_review', 'finalized'].includes(data.phase)) return false
  if (typeof data.data_quality?.ok !== 'boolean' || !data.total || !data.champion) return false
  const names = new Set(data.groups.map(group => group.name))
  if (names.size !== 8 || !Array.isArray(data.champion.names)) return false
  if (!data.groups.every(group => typeof group.name === 'string' && integer(group.done) && integer(group.target)
    && group.target > 0 && finite(group.rate) && integer(group.members) && integer(group.excess)
    && integer(group.remaining) && typeof group.solo === 'boolean' && typeof group.first === 'boolean'
    && typeof group.achieved === 'boolean')) return false
  if (data.total.target !== data.groups.reduce((sum, group) => sum + group.target, 0)) return false
  if (!data.champion.names.every(name => names.has(name))) return false
  if (data.groups.some(group => group.first !== data.champion.names.includes(group.name))) return false
  if (data.groups.some(group => group.first && (group.solo || group.members < 2 || group.done < group.target))) return false
  if (data.data_quality.ok) {
    return integer(data.total.done) && finite(data.total.rate) && integer(data.total.remaining)
      && integer(data.total.excess) && integer(data.total.achieved_groups)
      && data.total.done === data.groups.reduce((sum, group) => sum + group.done, 0)
  }
  return data.total.done === null && data.champion.names.length === 0
}

export function snapshotIsStale(data, now = Date.now()) {
  const asOf = parseApiDateTime(data?.as_of)
  return !asOf || now - asOf.getTime() > 5 * 60 * 1000
}

export function screenUrl(filename, search) {
  // Only preserve known screen controls; never carry arbitrary navigation targets.
  const source = new URLSearchParams(search)
  const query = new URLSearchParams()
  for (const name of ['key', 'stay', 'preview', 'date_from', 'date_to', 'source']) {
    if (source.has(name)) query.set(name, source.get(name))
  }
  return `/festival/${filename}${query.size ? `?${query}` : ''}`
}
