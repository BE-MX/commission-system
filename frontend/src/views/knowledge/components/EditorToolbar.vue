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
      <select v-if="structuredAuthoring" aria-label="字号" :value="fontSize" @change="setFontSize($event.target.value)">
        <option value="">字号</option>
        <option v-for="size in FONT_SIZES" :key="size" :value="size">{{ size }} px</option>
      </select>
      <select v-if="structuredAuthoring" aria-label="段落对齐" :value="alignment" @change="setAlignment($event.target.value)">
        <option value="">对齐</option>
        <option v-for="option in TEXT_ALIGNMENTS" :key="option.value" :value="option.value">{{ option.label }}</option>
      </select>
    </div>
    <div class="tool-group">
      <button :class="{ active: editor.isActive('bold') }" title="加粗 Ctrl+B" @mousedown.prevent="run('bold')"><strong>B</strong></button>
      <button :class="{ active: editor.isActive('italic') }" title="斜体 Ctrl+I" @mousedown.prevent="run('italic')"><em>I</em></button>
      <button :class="{ active: editor.isActive('strike') }" title="删除线 Ctrl+Shift+S" @mousedown.prevent="run('strike')"><s>S</s></button>
      <button v-if="structuredAuthoring" :class="{ active: editor.isActive('underline') }" type="button" title="下划线 Ctrl+U" aria-label="下划线" @mousedown.prevent @click="run('underline')"><u>U</u></button>
      <button :class="{ active: editor.isActive('code') }" title="行内代码 Ctrl+E" @mousedown.prevent="run('code')">&lt;/&gt;</button>
      <button :class="{ active: editor.isActive('link') }" title="插入或编辑链接 Ctrl+K" @mousedown.prevent="$emit('edit-link')">🔗</button>
      <button title="插入图片" @mousedown.prevent="$emit('insert-image')">图片</button>
      <TextColorPicker :editor="editor" :version="version" />
      <TextColorPicker v-if="structuredAuthoring" :editor="editor" :version="version" highlight />
      <button v-if="structuredAuthoring" type="button" title="清除文字格式" aria-label="清除文字格式" @mousedown.prevent @click="clearTextFormatting">清除格式</button>
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
      <button type="button" title="插入 3×3 表格" aria-label="插入 3×3 表格" @mousedown.prevent @click="run('table')">▦</button>
      <button v-if="structuredAuthoring" type="button" aria-label="插入" aria-haspopup="listbox" :aria-expanded="insertOpen" @mousedown.prevent @click="$emit('open-insert', $event.currentTarget)">＋ 插入</button>
    </div>
    <div v-if="editor.isActive('table')" class="tool-group table-tools" aria-label="表格操作">
      <button title="左侧增加列" @mousedown.prevent="table('addColumnBefore')">列＋←</button>
      <button title="右侧增加列" @mousedown.prevent="table('addColumnAfter')">列＋→</button>
      <button title="上方增加行" @mousedown.prevent="table('addRowBefore')">行＋↑</button>
      <button title="下方增加行" @mousedown.prevent="table('addRowAfter')">行＋↓</button>
      <button title="删除列" @mousedown.prevent="table('deleteColumn')">删列</button>
      <button title="删除行" @mousedown.prevent="table('deleteRow')">删行</button>
      <button v-if="structuredAuthoring" type="button" title="合并选中的单元格" :disabled="!editor.can().mergeCells()" @mousedown.prevent @click="table('mergeCells')">合并单元格</button>
      <button v-if="structuredAuthoring" type="button" title="拆分光标所在的合并单元格" :disabled="!editor.can().splitCell()" @mousedown.prevent @click="table('splitCell')">拆分单元格</button>
      <button title="切换表头行" @mousedown.prevent="table('toggleHeaderRow')">表头</button>
      <button class="danger" title="删除表格" @mousedown.prevent="table('deleteTable')">删表</button>
    </div>
    <span class="shortcut-hint">输入 / 快速插入</span>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import TextColorPicker from './TextColorPicker.vue'
import { FONT_SIZES, TEXT_ALIGNMENTS } from './knowledgeAuthoring.js'
import { runBlockCommand } from './editorConfig.js'

const props = defineProps({
  editor: { type: Object, required: true },
  version: { type: Number, default: 0 },
  insertOpen: Boolean,
  structuredAuthoring: Boolean,
})
defineEmits(['edit-link', 'insert-image', 'open-insert'])

const blockType = computed(() => {
  void props.version
  for (let level = 1; level <= 6; level += 1) {
    if (props.editor.isActive('heading', { level })) return `heading-${level}`
  }
  return 'paragraph'
})

const fontSize = computed(() => {
  void props.version
  return props.editor.getAttributes('knowledgeTextSize').size ?? ''
})

const alignment = computed(() => {
  void props.version
  return TEXT_ALIGNMENTS.find(({ value }) => props.editor.isActive({ textAlign: value }))?.value ?? ''
})

function run(command) {
  const actions = {
    undo: 'undo', redo: 'redo', bold: 'toggleBold', italic: 'toggleItalic',
    strike: 'toggleStrike', underline: 'toggleUnderline', code: 'toggleCode',
  }
  if (actions[command]) props.editor.chain().focus()[actions[command]]().run()
  else runBlockCommand(props.editor, command)
}

function setBlockType(value) {
  runBlockCommand(props.editor, value)
}

function setFontSize(value) {
  const chain = props.editor.chain().focus()
  if (!value) chain.unsetMark('knowledgeTextSize').run()
  else if (FONT_SIZES.includes(Number(value))) chain.setMark('knowledgeTextSize', { size: Number(value) }).run()
}

function setAlignment(value) {
  const chain = props.editor.chain().focus()
  if (value) chain.setTextAlign(value).run()
  else chain.unsetTextAlign().run()
}

function clearTextFormatting() {
  const chain = props.editor.chain().focus()
  for (const mark of ['bold', 'italic', 'strike', 'underline', 'code', 'textColor', 'knowledgeTextSize', 'knowledgeHighlight']) {
    chain.unsetMark(mark)
  }
  chain.run()
}

function table(command) {
  props.editor.chain().focus()[command]().run()
}
</script>

<style scoped>
.editor-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; padding: 5px 14px; border-bottom: 1px solid var(--border-color); background: var(--toolbar-bg); }
.tool-group { display: flex; align-items: center; gap: 2px; padding-right: 4px; border-right: 1px solid var(--border-color); }
.tool-group:last-of-type { border-right: 0; }
button, select { height: 30px; border: 1px solid transparent; border-radius: 6px; color: var(--text-secondary); background: transparent; font: inherit; font-size: 13px; }
button { min-width: 30px; padding: 0 6px; cursor: pointer; transition: transform 120ms cubic-bezier(.23,1,.32,1), color 120ms ease, background-color 120ms ease; }
button:active:not(:disabled) { transform: scale(.97); }
button.active { color: var(--button-primary); background: var(--button-primary-soft); }
button.danger { color: var(--button-danger); }
button:disabled { opacity: .35; cursor: not-allowed; }
button:focus-visible { outline: 2px solid var(--button-primary); outline-offset: 1px; }
select:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 1px; }
select { max-width: 104px; padding: 0 24px 0 8px; border-color: var(--border-color); cursor: pointer; }
.table-tools button { width: auto; font-size: 12px; }
.shortcut-hint { margin-left: auto; color: var(--text-muted-blue); font-size: 11px; white-space: nowrap; }
@media (hover: hover) and (pointer: fine) {
  button:hover:not(:disabled) { color: var(--button-primary); background: var(--button-primary-soft); }
  button.danger:hover:not(:disabled) { color: var(--button-danger-hover); background: var(--button-danger-soft); }
  select:hover { color: var(--color-primary-text); background: var(--color-primary-light); }
}
@media (prefers-reduced-motion: reduce) { button { transition: color 120ms ease, background-color 120ms ease; } button:active:not(:disabled) { transform: none; } }
</style>
