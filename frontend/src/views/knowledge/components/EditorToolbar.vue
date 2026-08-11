<template>
  <div class="editor-toolbar" aria-label="文档格式工具栏" role="toolbar">
    <div class="tool-group">
      <button title="撤销 Ctrl+Z" :disabled="!editor.can().undo()" @mousedown.prevent="run('undo')">↶</button>
      <button title="重做 Ctrl+Shift+Z" :disabled="!editor.can().redo()" @mousedown.prevent="run('redo')">↷</button>
    </div>
    <div class="tool-group">
      <select aria-label="段落格式" :value="blockType" @change="setBlockType($event.target.value)">
        <option value="paragraph">正文</option>
        <option v-for="level in 6" :key="level" :value="`heading-${level}`">标题 {{ level }}</option>
      </select>
    </div>
    <div class="tool-group">
      <button :class="{ active: editor.isActive('bold') }" title="加粗 Ctrl+B" @mousedown.prevent="run('bold')"><strong>B</strong></button>
      <button :class="{ active: editor.isActive('italic') }" title="斜体 Ctrl+I" @mousedown.prevent="run('italic')"><em>I</em></button>
      <button :class="{ active: editor.isActive('strike') }" title="删除线 Ctrl+Shift+S" @mousedown.prevent="run('strike')"><s>S</s></button>
      <button :class="{ active: editor.isActive('code') }" title="行内代码 Ctrl+E" @mousedown.prevent="run('code')">&lt;/&gt;</button>
      <button :class="{ active: editor.isActive('link') }" title="插入或编辑链接 Ctrl+K" @mousedown.prevent="$emit('edit-link')">🔗</button>
      <TextColorPicker :editor="editor" :version="version" />
    </div>
    <div class="tool-group">
      <button :class="{ active: editor.isActive('bulletList') }" title="无序列表" @mousedown.prevent="run('bullet-list')">•</button>
      <button :class="{ active: editor.isActive('orderedList') }" title="有序列表" @mousedown.prevent="run('ordered-list')">1.</button>
      <button :class="{ active: editor.isActive('taskList') }" title="任务列表" @mousedown.prevent="run('task-list')">☑</button>
      <button :class="{ active: editor.isActive('blockquote') }" title="引用" @mousedown.prevent="run('blockquote')">❝</button>
      <button :class="{ active: editor.isActive('codeBlock') }" title="代码块" @mousedown.prevent="run('code-block')">{ }</button>
      <button title="分割线" @mousedown.prevent="run('horizontal-rule')">―</button>
    </div>
    <div class="tool-group">
      <button title="插入 3×3 表格" @mousedown.prevent="run('table')">▦</button>
    </div>
    <div v-if="editor.isActive('table')" class="tool-group table-tools" aria-label="表格操作">
      <button title="左侧增加列" @mousedown.prevent="table('addColumnBefore')">列＋←</button>
      <button title="右侧增加列" @mousedown.prevent="table('addColumnAfter')">列＋→</button>
      <button title="上方增加行" @mousedown.prevent="table('addRowBefore')">行＋↑</button>
      <button title="下方增加行" @mousedown.prevent="table('addRowAfter')">行＋↓</button>
      <button title="删除列" @mousedown.prevent="table('deleteColumn')">删列</button>
      <button title="删除行" @mousedown.prevent="table('deleteRow')">删行</button>
      <button title="切换表头行" @mousedown.prevent="table('toggleHeaderRow')">表头</button>
      <button class="danger" title="删除表格" @mousedown.prevent="table('deleteTable')">删表</button>
    </div>
    <span class="shortcut-hint">输入 / 快速插入</span>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import TextColorPicker from './TextColorPicker.vue'

const props = defineProps({ editor: { type: Object, required: true }, version: { type: Number, default: 0 } })
defineEmits(['edit-link'])

const blockType = computed(() => {
  void props.version
  for (let level = 1; level <= 6; level += 1) {
    if (props.editor.isActive('heading', { level })) return `heading-${level}`
  }
  return 'paragraph'
})

function run(command) {
  const chain = props.editor.chain().focus()
  const actions = {
    undo: () => chain.undo().run(), redo: () => chain.redo().run(),
    bold: () => chain.toggleBold().run(), italic: () => chain.toggleItalic().run(),
    strike: () => chain.toggleStrike().run(), code: () => chain.toggleCode().run(),
    'bullet-list': () => chain.toggleBulletList().run(), 'ordered-list': () => chain.toggleOrderedList().run(),
    'task-list': () => chain.toggleTaskList().run(), blockquote: () => chain.toggleBlockquote().run(),
    'code-block': () => chain.toggleCodeBlock().run(), 'horizontal-rule': () => chain.setHorizontalRule().run(),
    table: () => chain.insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run(),
  }
  actions[command]?.()
}

function setBlockType(value) {
  const chain = props.editor.chain().focus()
  if (value === 'paragraph') chain.setParagraph().run()
  else chain.toggleHeading({ level: Number(value.split('-')[1]) }).run()
}

function table(command) {
  props.editor.chain().focus()[command]().run()
}
</script>

<style scoped>
.editor-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; padding: 5px 14px; border-bottom: 1px solid var(--border-color); background: var(--surface-subtle); }
.tool-group { display: flex; align-items: center; gap: 2px; padding-right: 4px; border-right: 1px solid var(--border-color); }
.tool-group:last-of-type { border-right: 0; }
button, select { height: 30px; border: 1px solid transparent; border-radius: 6px; color: var(--text-secondary); background: transparent; font: inherit; font-size: 13px; }
button { min-width: 30px; padding: 0 6px; cursor: pointer; transition: transform 120ms cubic-bezier(.23,1,.32,1), color 120ms ease, background-color 120ms ease; }
button:active:not(:disabled) { transform: scale(.97); }
button.active { color: var(--color-primary); background: var(--color-primary-light); }
button.danger { color: var(--color-danger); }
button:disabled { opacity: .35; cursor: not-allowed; }
button:focus-visible, select:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 1px; }
select { max-width: 104px; padding: 0 24px 0 8px; border-color: var(--border-color); cursor: pointer; }
.table-tools button { width: auto; font-size: 12px; }
.shortcut-hint { margin-left: auto; color: var(--text-muted-blue); font-size: 11px; white-space: nowrap; }
@media (hover: hover) and (pointer: fine) { button:hover:not(:disabled), select:hover { color: var(--color-primary); background: var(--color-primary-light); } }
@media (prefers-reduced-motion: reduce) { button { transition: color 120ms ease, background-color 120ms ease; } button:active:not(:disabled) { transform: none; } }
</style>
