import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
let serial = 0
async function apiFor(payload) {
  let source = fs.readFileSync(new URL('../src/api/perfGoal.js', import.meta.url), 'utf8')
  source = source.replace("import { perfGoalClient as client } from './clients'", `const client = { get: async () => (${JSON.stringify({ code: 200, message: 'ok', data: payload })}) }`)
  source = source.replace("from './perfGoalPayload.js'", `from '${new URL('../src/api/perfGoalPayload.js', import.meta.url).href}'`)
  return (await import(`data:text/javascript;base64,${Buffer.from(source + '\n// ' + serial++).toString('base64')}`)).perfGoalApi
}
test('actual API adapter preserves a successful null active period instead of returning the truthy envelope', async () => {
  assert.equal(await (await apiFor(null)).activePeriod(), null)
})
test('wire ratios become UI percentages exactly once while percentage-point differences and money stay unchanged', async () => {
  const payload = { time_progress: 0.25, metrics: { gmv: { target: 200, achieved: 100, rate: 0.5, prev_rate: 1.2, delta_pp: 25 } }, warnings: [{ projected_rate: 1.25, gap: 100 }] }
  const view = await (await apiFor(payload)).overview({})
  assert.equal(view.time_progress, 25); assert.equal(view.metrics.gmv.rate, 50)
  assert.equal(view.metrics.gmv.prev_rate, 120); assert.equal(view.metrics.gmv.delta_pp, 25)
  assert.equal(view.metrics.gmv.achieved, 100); assert.equal(view.warnings[0].projected_rate, 125)
})
test('team and ranking adapters preserve IDs and amounts and normalize all ratio cells, including overachievement', async () => {
  const payload = { rows: [{ department_id: 1, user_id: 2, overall_rate: 1.2, metrics: { gmv: { rate: 0.5, achieved: 99 } }, members: [{ user_id: 3, gmv_rate: 0.8 }], gmv: { rate: 1.2, target: 50 }, delta_pp: 20 }] }
  const api = await apiFor(payload), teams = await api.teams({}), ranking = await api.ranking({})
  assert.equal(teams.rows[0].overall_rate, 120); assert.equal(teams.rows[0].metrics.gmv.rate, 50)
  assert.equal(teams.rows[0].members[0].gmv_rate, 80); assert.equal(teams.rows[0].metrics.gmv.achieved, 99)
  assert.equal(ranking.rows[0].gmv.rate, 120); assert.equal(ranking.rows[0].delta_pp, 20); assert.equal(ranking.rows[0].user_id, 2)
})
