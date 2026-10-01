/** 任务树的纯函数：筛选、看板分列、模块热度、父标题索引。 */
import { BOARD_COLUMNS, CLOSED } from './taskLabels.js'

function selfMatches(task, filters) {
  const q = (filters.q || '').trim().toLowerCase()
  if (q && !(`t-${task.id}`.includes(q) || task.title.toLowerCase().includes(q))) return false
  if (filters.moduleKey && task.module_key !== filters.moduleKey) return false
  if (filters.priorities?.length && !filters.priorities.includes(task.priority)) return false
  if (filters.hideClosed && CLOSED.has(task.status)) return false
  return true
}

/** 保留自身命中或有后代命中的节点；返回新树，不修改入参。 */
export function filterTree(nodes, filters = {}) {
  const out = []
  for (const node of nodes) {
    const children = filterTree(node.children || [], filters)
    if (selfMatches(node, filters) || children.length) out.push({ ...node, children })
  }
  return out
}

export function collectLeaves(nodes, acc = []) {
  for (const node of nodes) {
    if (node.children?.length) collectLeaves(node.children, acc)
    else acc.push(node)
  }
  return acc
}

/** 看板只放叶子任务；已搁置不上板；「已完成」列始终显示，所以忽略 hideClosed。 */
export function boardColumns(nodes, filters = {}) {
  const cols = Object.fromEntries(BOARD_COLUMNS.map(s => [s, []]))
  const leaves = collectLeaves(nodes).filter(t => selfMatches(t, { ...filters, hideClosed: false }))
  for (const task of leaves) {
    if (cols[task.status]) cols[task.status].push(task)
  }
  return cols
}

/** 按模块分组统计未结束叶子数；modules 顺序即展示顺序。 */
export function moduleHeat(nodes, modules) {
  const open = collectLeaves(nodes).filter(t => !CLOSED.has(t.status))
  const groups = new Map()
  for (const m of modules) {
    if (!groups.has(m.group_key)) groups.set(m.group_key, { group_key: m.group_key, group_title: m.group_title, open: 0, items: [] })
    const mine = open.filter(t => t.module_key === m.key)
    const group = groups.get(m.group_key)
    group.items.push({ key: m.key, title: m.title, open: mine.length, hasP0: mine.some(t => t.priority === 'P0'), isPrivate: Boolean(m.is_private) })
    group.open += mine.length
  }
  return [...groups.values()]
}

export function findNode(nodes, id) {
  for (const node of nodes) {
    if (node.id === id) return node
    const found = findNode(node.children || [], id)
    if (found) return found
  }
  return null
}

/** 某任务下未结束的子孙数：标记完成前的确认文案用（后端仍会校验）。 */
export function openDescendantCount(nodes, id) {
  let count = 0
  const walk = list => {
    for (const node of list) {
      if (!CLOSED.has(node.status)) count += 1
      walk(node.children || [])
    }
  }
  walk(findNode(nodes, id)?.children || [])
  return count
}

export function parentTitles(nodes, parent = null, map = new Map()) {
  for (const node of nodes) {
    if (parent) map.set(node.id, parent.title)
    parentTitles(node.children || [], node, map)
  }
  return map
}

/** 下拉选择父任务用：扁平化并带缩进层级。 */
export function flattenForSelect(nodes, depth = 0, acc = []) {
  for (const node of nodes) {
    if (!CLOSED.has(node.status)) acc.push({ id: node.id, label: `${'　'.repeat(depth)}T-${node.id} ${node.title}`, depth })
    flattenForSelect(node.children || [], depth + 1, acc)
  }
  return acc
}
