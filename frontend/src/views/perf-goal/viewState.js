import { goalKey } from './helpers.js'

// UI selection only; metric calculations and server authorization stay in the domain API.
export const canEditGoalPerson = person => person?.user_id != null && String(person.user_id).trim() !== '' && Number(person.user_id) > 0
export const isValidGoalInput = value => String(value ?? '').trim() !== '' && Number.isFinite(Number(value)) && Number(value) >= 0
export const teamGoalRowKey = row => [row.department_id, row.metric, row.granularity, row.quarter ?? '', row.month ?? ''].join('|')
export const selectTeamGoalRows = (rows, metric, granularity) => (rows || []).filter(row => row.metric === metric && row.granularity === granularity)

export function perfRosterPeople(roster = {}) {
  const people = [...(roster.teams || []).flatMap(team => (team.members || []).map(person => ({ ...person, team_name: team.name, department_id: team.department_id }))), ...(roster.unassigned || []).map(person => ({ ...person, team_name: '未分组', department_id: null }))]
  return [...new Map(people.filter(canEditGoalPerson).map(person => [String(person.user_id), person])).values()]
}
export function perfViewAccess(user, roster = {}) {
  if (!user) return { company: false, compare: false, teams: [], people: [], defaultScope: 'person', defaultId: null }
  const all = (user.roles || []).some(role => ['super_admin', 'admin', 'supervisor'].includes(role)) || (user.permissions || []).includes('perf_goal:admin')
  const ownTeams = (roster.teams || []).filter(team => team.captain_user_id != null && String(team.captain_user_id) === String(user.id)).slice(0, 1)
  const teams = all ? roster.teams || [] : ownTeams
  const people = perfRosterPeople(roster).filter(person => all || String(person.user_id) === String(user.id) || ownTeams.some(team => String(team.department_id) === String(person.department_id)))
  return { company: all, compare: all || !!ownTeams.length, teams, people, defaultScope: all ? 'company' : ownTeams.length ? 'team' : 'person', defaultId: all ? null : ownTeams[0]?.department_id ?? people.find(person => String(person.user_id) === String(user.id))?.user_id ?? null }
}
export function selectedPerfRange({ year, period_type = 'year', quarter = 1, month = 1 }, asOf) {
  const first = period_type === 'month' ? month : period_type === 'quarter' ? (quarter - 1) * 3 + 1 : 1
  const last = period_type === 'month' ? month : period_type === 'quarter' ? first + 2 : 12
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
  const date = (m, d) => `${year}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`
  const start = date(first, 1), end = date(last, days[last - 1])
  return { range: [start, asOf < end && asOf >= start ? asOf : end], notStarted: asOf < start }
}

export const childGoalKey = (userId, metric, granularity, index) => granularity === 'quarter'
  ? goalKey(userId, metric, granularity, index, null)
  : goalKey(userId, metric, granularity, Math.floor((index - 1) / 3) + 1, index)
export function teamGoalUpdate(row, factorDraft, overrideDraft) {
  const hasFactor = Object.hasOwn(factorDraft, row.department_id), hasOverride = Object.hasOwn(overrideDraft, row.department_id)
  const clear = hasOverride && String(overrideDraft[row.department_id]).trim() === ''
  return { department_id: row.department_id, metric: row.metric, granularity: row.granularity, quarter: row.quarter ?? null, month: row.month ?? null,
    factor: hasFactor ? Number(factorDraft[row.department_id]) / 100 : row.factor,
    override_value: hasOverride ? clear ? null : Number(overrideDraft[row.department_id]) : row.override_value,
    clear_override: clear }
}
export function splitPreviewByPerson(preview, target) {
  const people = new Map(), count = target === 'quarter' ? 4 : 12
  for (const row of preview || []) {
    const key = String(row.user_id)
    if (!people.has(key)) people.set(key, { user_id: row.user_id, user_name: row.user_name, entries: Array(count).fill(null) })
    for (const entry of row.entries || []) {
      const index = (target === 'quarter' ? entry.quarter : entry.month) - 1
      if (index >= 0 && index < count) people.get(key).entries[index] = entry
    }
  }
  return [...people.values()].filter(row => row.entries.some(Boolean))
}
