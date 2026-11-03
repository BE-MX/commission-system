import test from 'node:test'
import assert from 'node:assert/strict'
import { accessibleNavigationSections as resolve, quickNavigationItems as flatten, filterNavigationSections } from '../src/views/layout/navigationSearch.js'
import { resolveFavoriteItems } from '../src/views/layout/favoriteNavigationState.js'
const groups = { restricted: { title: 'Restricted', permission: 'group:read' }, open: { title: 'Open' } }
const entries = [{ name: 'A', path: '/a', title: 'A', permission: 'page:read', menu: { group: 'restricted', title: 'Original', order: 1, badge: 'domesticReviews' } }, { name: 'B', path: '/b', title: 'B', menu: { group: 'open', title: 'B', order: 2 } }]
const auth = permissions => ({ user: { id: 1 }, hasPermission: code => permissions.includes(code), hasAnyPermission: codes => codes.some(code => permissions.includes(code)) })
const nodes = [{ id: 'custom-first', kind: 'group', label: 'First', parent: null }, { id: 'custom-second', kind: 'group', label: 'Second', parent: 'custom-first' }, { id: 'A', kind: 'page', label: 'Alias', parent: 'custom-second', badge: 'NEW' }]
test('moved entries retain source group permission and empty destination groups disappear', () => {
  const result = resolve(entries, groups, auth(['page:read']), {}, nodes)
  assert.deepEqual(flatten(result).map(item => item.name), ['B'])
})
test('two-level group aliases synchronize search and saved favorites without overriding business badge', () => {
  const result = resolve(entries, groups, auth(['page:read', 'group:read']), {}, nodes)
  const item = flatten(result, 'Alias Second')[0]
  assert.equal(item.name, 'A'); assert.equal(item.groupTitle, 'First / Second')
  assert.equal(item.badge, 'domesticReviews'); assert.equal(item.textBadge, 'NEW')
  assert.equal(resolveFavoriteItems(['A'], flatten(result))[0].title, 'Alias')
  assert.equal(filterNavigationSections([], result.groups, 'Alias').groups[0].items[0].items[0].name, 'A')
})
test('hidden ancestor suppresses all surfaces while source defaults and phase checks remain valid', () => {
  const user = auth(['page:read', 'group:read'])
  assert.deepEqual(flatten(resolve(entries, groups, user)).map(item => item.title), ['Original', 'B'])
  assert.deepEqual(resolveFavoriteItems(['A'], flatten(resolve(entries, groups, user, {}, [...nodes, { ...nodes[0], visible: false }]))), [])
  const phased = [{ ...entries[0], menu: { ...entries[0].menu, commercePhases: ['independent'] } }]
  assert.equal(flatten(resolve(phased, groups, user, { commercePhase: null }, nodes)).length, 0)
})
