// 全站统一的枚举字典：标签 + 语义色（映射到 base.css 的 badge 变体类，不写裸色）

export const MATERIAL_STATUS = {
  not_started: { label: '未开始', tone: 'muted' },
  preparing: { label: '准备中', tone: 'slate' },
  submitted: { label: '已提交', tone: 'amber' },
  confirmed: { label: '顾问确认', tone: 'sage' },
  not_required: { label: '无需提供', tone: 'muted' },
}
export const MATERIAL_STATUS_FLOW = ['not_started', 'preparing', 'submitted', 'confirmed']

export const IMPORTANCE = {
  required: { label: '必须', tone: 'cinnabar', mark: '●' },
  important: { label: '重要', tone: 'amber', mark: '●' },
  optional: { label: '锦上添花', tone: 'sage', mark: '●' },
}

export const DELIVERY_TYPE = {
  file: { label: '文件', icon: '↥' },
  offline: { label: '线下交付', icon: '⇄' },
  link: { label: '外部链接', icon: '↗' },
}

export const TASK_STATUS = {
  todo: { label: '待办', tone: 'muted' },
  in_progress: { label: '进行中', tone: 'slate' },
  done: { label: '已完成', tone: 'sage' },
  blocked: { label: '受阻', tone: 'cinnabar' },
}
export const TASK_STATUS_ORDER = ['todo', 'in_progress', 'done', 'blocked']

export const DIFF_STATUS = {
  pending: { label: 'AI 差异概要生成中', tone: 'slate' },
  done: { label: 'AI 差异概要', tone: 'sage' },
  failed: { label: '差异概要生成失败', tone: 'cinnabar' },
  not_applicable: { label: '不支持对比', tone: 'muted' },
}

export const CATEGORY_ORDER = ['产品与报价', '客户分类与分配', '知识与内容', '系统权限与账号', '历史数据', '其他']

export const PHASES = [1, 2, 3, 4]

export function fmtTime(iso, withTime = true) {
  if (!iso) return '—'
  const s = String(iso).replace('T', ' ')
  return withTime ? s.slice(0, 16) : s.slice(0, 10)
}

export function fmtSize(bytes) {
  if (bytes == null) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function relTime(iso) {
  if (!iso) return ''
  const then = new Date(String(iso).replace(' ', 'T'))
  const diff = Date.now() - then.getTime() - 8 * 3600 * 1000 * 0 // 服务器时间即北京时间
  const abs = Math.abs(diff)
  const mins = Math.round(diff / 60000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins} 分钟前`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.round(hours / 24)
  if (days < 30) return `${days} 天前`
  return fmtTime(iso, false)
}
