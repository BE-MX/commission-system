import test from 'node:test'
import assert from 'node:assert/strict'
import { mergeNodes, nextSiblingOrder, validateNodes, writableNodes, reorderNode, diffNodes } from './navigationEditor.js'
const node = (id, label, parent = '', kind = 'group') => ({ id, label, parent, kind, order: 0, icon: 'Folder', visible: true, badge: '', badgePlace: 'text', badgeTone: 'gold', titleSync: false })
test('catalog authority cannot be replaced by draft fields', () => {
 const result = mergeNodes([{ ...node('g', 'G'), builtin: true, protected: true }], [{ ...node('g', 'G'), protected: false, builtin: false }])
 assert.equal(result[0].protected, true); assert.equal(result[0].builtin, true)
 assert.equal('protected' in writableNodes(result)[0], false)
})
test('cycles and excessive depth fail while legal second-level groups pass', () => {
 const legal = [node('a', 'A'), node('b', 'B', 'a'), node('c', 'C', 'b', 'page')]
 assert.deepEqual(validateNodes(legal, ['Folder']), [])
 assert.ok(validateNodes([...legal, node('d', 'D', 'b')], ['Folder']).some(e => e.message.includes('最多两级')))
 legal[0].parent = 'b'; assert.ok(validateNodes(legal, ['Folder']).some(e => e.message.includes('循环')))
})
test('unicode normalization prevents duplicate sibling names', () => {
 assert.ok(validateNodes([node('a', 'Ａ'), node('b', 'a')], ['Folder']).some(e => e.message.includes('重复')))
})
test('reorder refuses cross-parent movement and normalizes sibling order', () => {
 const list = [node('a', 'A'), { ...node('b', 'B'), order: 2 }, node('c', 'C', 'a')]
 assert.equal(reorderNode(list, 'a', 'c'), false)
 assert.equal(reorderNode(list, 'b', 'a'), true)
 assert.equal(list[1].order, 0); assert.equal(list[0].order, 1)
})
test('publish diff includes hiding and removal', () => {
 const before = [node('a', 'A'), node('b', 'B')]
 const changes = diffNodes(before, [{ ...before[0], visible: false }])
 assert.ok(changes.some(c => c.field === '显示' && c.after === 'false'))
 assert.ok(changes.some(c => c.field === '删除' && c.id === 'b'))
})

test('renamed entries retain catalog label and appended groups follow sparse orders', () => {
 const catalog = [{ ...node('g', 'Original'), order: 20 }, { ...node('h', 'Other'), order: 70 }]
 const merged = mergeNodes(catalog, [{ ...catalog[0], label: 'Alias' }])
 assert.equal(merged[0].originalLabel, 'Original'); assert.equal(merged[1].originalLabel, 'Other')
 assert.equal(nextSiblingOrder(merged), 71)
 assert.equal(nextSiblingOrder([...merged, { ...node('moving', 'Moved'), order: 999 }], '', 'moving'), 71)
 assert.equal(nextSiblingOrder(merged, 'empty'), 0)
})
