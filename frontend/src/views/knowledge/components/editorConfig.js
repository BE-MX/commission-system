export const EDITOR_COMMANDS = [
  { id: 'paragraph', label: '正文', description: '普通段落', keywords: ['text', 'paragraph', '正文', '段落'] },
  ...Array.from({ length: 6 }, (_, index) => ({
    id: `heading-${index + 1}`,
    label: `标题 ${index + 1}`,
    description: `H${index + 1} 标题`,
    keywords: [`h${index + 1}`, `heading ${index + 1}`, `标题${index + 1}`],
  })),
  { id: 'bullet-list', label: '无序列表', description: '项目符号列表', keywords: ['bullet', 'list', '无序', '列表'] },
  { id: 'ordered-list', label: '有序列表', description: '数字编号列表', keywords: ['ordered', 'numbered', 'list', '有序', '编号'] },
  { id: 'task-list', label: '任务列表', description: '带复选框的待办事项', keywords: ['task', 'todo', 'check', '任务', '待办'] },
  { id: 'blockquote', label: '引用', description: '引用段落', keywords: ['quote', 'blockquote', '引用'] },
  { id: 'code-block', label: '代码块', description: '多行代码内容', keywords: ['code', '代码'] },
  { id: 'horizontal-rule', label: '分割线', description: '分隔内容区块', keywords: ['divider', 'rule', '分割', '分隔'] },
  { id: 'table', label: '表格', description: '插入 3×3 表格', keywords: ['table', 'grid', '表格'] },
]

export function filterEditorCommands(commands, query) {
  const normalized = query.trim().toLocaleLowerCase()
  if (!normalized) return commands
  return commands.filter(item => [item.label, item.description, ...item.keywords]
    .some(value => value.toLocaleLowerCase().includes(normalized)))
}

function textContent(node) {
  if (node.type === 'text') return node.text || ''
  return (node.content || []).map(textContent).join('')
}

export function extractOutline(document) {
  const headings = []
  function walk(node) {
    if (node?.type === 'heading') {
      const text = textContent(node).trim()
      if (text) {
        const index = headings.length
        headings.push({ id: `heading-${index}`, level: node.attrs?.level || 1, text, index })
      }
    }
    for (const child of node?.content || []) walk(child)
  }
  walk(document)
  return headings
}

export function saveStatusLabel(state, options = {}) {
  if (state.error) return '保存失败，请重试'
  if (state.saving) return '正在保存…'
  if (state.dirty) return '有未保存修改'
  if (!state.savedAt) return '已保存'
  const locale = options.locale || 'zh-CN'
  const formatterOptions = { hour: '2-digit', minute: '2-digit', hour12: false }
  if (options.timeZone) formatterOptions.timeZone = options.timeZone
  return `已保存 ${new Intl.DateTimeFormat(locale, formatterOptions).format(state.savedAt)}`
}
