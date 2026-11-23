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
  { id: 'image', label: '图片', structuredAuthoring: true, description: '上传本地图片', keywords: ['image', '图片', '插图'] },
  { id: 'table', label: '表格', description: '插入 3×3 表格', keywords: ['table', 'grid', '表格'] },
  { id: 'callout', label: '高亮块', structuredAuthoring: true, description: '突出显示说明或重点', keywords: ['callout', '高亮', '提醒', '提示'] },
  { id: 'details', label: '折叠块', structuredAuthoring: true, description: '按需展开详细内容', keywords: ['details', 'collapse', '展开', '折叠'] },
]

export function filterEditorCommands(commands, query) {
  const normalized = query.trim().toLocaleLowerCase()
  if (!normalized) return commands
  return commands.filter(item => [item.label, item.description, ...item.keywords]
    .some(value => value.toLocaleLowerCase().includes(normalized)))
}

export function findSlashQuery(selection) {
  if (!selection.empty || !['paragraph', 'heading'].includes(selection.$from.parent.type.name)) return null
  const { $from } = selection
  const before = $from.parent.textBetween(0, $from.parentOffset, undefined, '\ufffc')
  const match = /^[/／]([^/／\n\ufffc]{0,40})$/u.exec(before)
  return match ? { from: $from.start(), to: $from.pos, query: match[1] } : null
}

export function runBlockCommand(editor, id, { range = null, toggle = true } = {}) {
  const actions = {
    paragraph: chain => chain.setParagraph(),
    'bullet-list': chain => chain.toggleBulletList(),
    'ordered-list': chain => chain.toggleOrderedList(),
    'task-list': chain => chain.toggleTaskList(),
    blockquote: chain => chain.toggleBlockquote(),
    'code-block': chain => chain.toggleCodeBlock(),
    'horizontal-rule': chain => chain.setHorizontalRule(),
    table: chain => chain.insertTable({ rows: 3, cols: 3, withHeaderRow: true }),
    callout: chain => toggle && editor.isActive('knowledgeCallout')
      ? chain.lift('knowledgeCallout')
      : chain.wrapIn('knowledgeCallout', { tone: 'info' }),
    details: chain => toggle && editor.isActive('details') ? chain.unsetDetails() : chain.setDetails(),
  }
  const heading = /^heading-([1-6])$/.exec(id)
  const apply = heading ? chain => chain.setHeading({ level: Number(heading[1]) }) : actions[id]
  if (!apply || !apply(editor.can().chain()).run()) return false
  let chain = editor.chain().focus()
  if (range) chain = chain.deleteRange(range)
  return apply(chain).run()
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
  const formatterOptions = { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Shanghai' }
  if (options.timeZone) formatterOptions.timeZone = options.timeZone
  return `已保存 ${new Intl.DateTimeFormat(locale, formatterOptions).format(state.savedAt)}`
}
