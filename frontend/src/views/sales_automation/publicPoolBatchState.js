export const PUBLIC_POOL_STATUS_TABS = [
  { key: 'pending_review', label: '待审核' },
  { key: 'pending', label: '待背调' },
  { key: 'running', label: '背调中' },
  { key: 'approved', label: '已通过' },
  { key: 'rejected', label: '已拒绝' },
  { key: 'failed', label: '异常' },
]

export function taskStatusBucket(task) {
  if (task.review_status === 'approved') return 'approved'
  if (task.review_status === 'rejected') return 'rejected'
  if (task.status === 'completed') return 'pending_review'
  if (task.status === 'running') return 'running'
  if (task.status === 'failed' || task.status === 'skipped') return 'failed'
  return 'pending'
}

export function taskStatusCounts(tasks = []) {
  const counts = Object.fromEntries(PUBLIC_POOL_STATUS_TABS.map(tab => [tab.key, 0]))
  for (const task of tasks) counts[taskStatusBucket(task)] += 1
  return counts
}

export function defaultBatchTab(tasks = []) {
  const counts = taskStatusCounts(tasks)
  return PUBLIC_POOL_STATUS_TABS.find(tab => counts[tab.key] > 0)?.key || 'pending_review'
}
