<template>
  <section v-if="document" class="editor-shell">
    <header class="editor-header">
      <div class="title-block">
        <el-input v-if="actions.canSave" v-model="title" class="title-input" maxlength="256" @input="markDirty" />
        <h1 v-else>{{ document.title }}</h1>
        <div class="document-meta">
          <el-tag effect="plain" :type="statusType">{{ statusLabel }}</el-tag>
          <span>版本 v{{ document.version_no || 1 }}</span>
          <span class="save-status" :class="{ error: saveError }">{{ saveLabel }}</span>
          <span v-if="document.pending_approval_id">审批中仍可编辑，新内容不会改变待审版本</span>
        </div>
      </div>
      <div class="header-actions">
        <GlassButton v-if="actions.canSave" variant="ghost" :loading="saving" :disabled="!dirty || saving" @click="save">保存草稿</GlassButton>
        <GlassButton v-if="actions.canSubmit" variant="primary" :disabled="dirty" @click="$emit('submit')">提交审批</GlassButton>
      </div>
    </header>

    <EditorToolbar v-if="editor && actions.canSave" :editor="editor" :version="editorVersion" @edit-link="editLink" />
    <div class="editor-body">
      <div ref="canvas" class="canvas-wrap" @keydown.capture="onEditorKeydown">
        <BubbleMenu
          v-if="editor && actions.canSave"
          :editor="editor"
          :should-show="({ from, to }) => from !== to && !editor.isActive('codeBlock')"
          :options="{ placement: 'top', offset: 8 }"
        >
          <div class="bubble-toolbar" aria-label="选中文本格式工具栏" role="toolbar">
            <button :class="{ active: editor.isActive('bold') }" title="加粗" @mousedown.prevent="editor.chain().focus().toggleBold().run()"><strong>B</strong></button>
            <button :class="{ active: editor.isActive('italic') }" title="斜体" @mousedown.prevent="editor.chain().focus().toggleItalic().run()"><em>I</em></button>
            <button :class="{ active: editor.isActive('strike') }" title="删除线" @mousedown.prevent="editor.chain().focus().toggleStrike().run()"><s>S</s></button>
            <button :class="{ active: editor.isActive('code') }" title="行内代码" @mousedown.prevent="editor.chain().focus().toggleCode().run()">&lt;/&gt;</button>
            <button :class="{ active: editor.isActive('link') }" title="链接" @mousedown.prevent="editLink">🔗</button>
          </div>
        </BubbleMenu>
        <EditorContent :editor="editor" class="document-canvas" :class="{ 'is-empty': editor?.isEmpty }" />
        <EditorSlashMenu
          :open="slashOpen"
          :items="filteredCommands"
          :active-index="slashIndex"
          :position="slashPosition"
          @activate="slashIndex = $event"
          @select="executeSlashCommand"
        />
      </div>
      <EditorOutline :items="outline" @navigate="navigateOutline" />
    </div>
  </section>

  <section v-else class="empty-editor">
    <el-empty description="从左侧选择文档开始阅读" :image-size="120" />
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { EditorContent, useEditor } from '@tiptap/vue-3'
import { BubbleMenu } from '@tiptap/vue-3/menus'
import StarterKit from '@tiptap/starter-kit'
import Link from '@tiptap/extension-link'
import { TaskItem, TaskList } from '@tiptap/extension-list'
import { Table } from '@tiptap/extension-table'
import TableRow from '@tiptap/extension-table-row'
import TableHeader from '@tiptap/extension-table-header'
import TableCell from '@tiptap/extension-table-cell'
import { documentActions } from '../knowledgeState.js'
import EditorOutline from './EditorOutline.vue'
import EditorSlashMenu from './EditorSlashMenu.vue'
import EditorToolbar from './EditorToolbar.vue'
import { EDITOR_COMMANDS, extractOutline, filterEditorCommands, saveStatusLabel } from './editorConfig.js'

const props = defineProps({ document: { type: Object, default: null }, role: { type: String, default: 'viewer' }, saving: Boolean })
const emit = defineEmits(['save', 'submit', 'dirty-change'])
const canvas = ref(null)
const title = ref('')
const dirty = ref(false)
const savedAt = ref(null)
const saveError = ref('')
const editorVersion = ref(0)
const outline = ref([])
const slashOpen = ref(false)
const slashQuery = ref('')
const slashIndex = ref(0)
const slashRange = ref(null)
const slashPosition = ref({ left: 0, top: 0 })
const actions = computed(() => documentActions({ role: props.role, status: props.document?.status, pendingApprovalId: props.document?.pending_approval_id }))
const statusLabel = computed(() => ({ draft: '草稿', pending: '待审批', published: '已发布' }[props.document?.status] || props.document?.status))
const statusType = computed(() => ({ draft: 'info', pending: 'warning', published: 'success' }[props.document?.status] || 'info'))
const saveLabel = computed(() => saveStatusLabel({ dirty: dirty.value, saving: props.saving, error: saveError.value, savedAt: savedAt.value }))
const filteredCommands = computed(() => filterEditorCommands(EDITOR_COMMANDS, slashQuery.value))

const editor = useEditor({
  editable: false,
  extensions: [
    StarterKit.configure({ link: false, underline: false }),
    Link.configure({ openOnClick: false, protocols: ['http', 'https', 'mailto'] }),
    TaskList, TaskItem.configure({ nested: true }),
    Table.configure({ resizable: true }), TableRow, TableHeader, TableCell,
  ],
  content: { type: 'doc', content: [{ type: 'paragraph' }] },
  onUpdate: ({ editor: instance }) => {
    markDirty()
    refreshDerivedState(instance)
    updateSlashQuery(instance)
  },
  onSelectionUpdate: ({ editor: instance }) => {
    editorVersion.value += 1
    if (slashOpen.value) updateSlashPosition(instance)
  },
})

function refreshDerivedState(instance = editor.value) {
  if (!instance) return
  outline.value = extractOutline(instance.getJSON())
  editorVersion.value += 1
}

function markDirty() {
  saveError.value = ''
  if (!dirty.value) {
    dirty.value = true
    emit('dirty-change', true)
  }
}

function resetDirty() {
  dirty.value = false
  savedAt.value = new Date()
  saveError.value = ''
  emit('dirty-change', false)
}

function failSave() {
  saveError.value = 'save_failed'
}

function save() {
  emit('save', { title: title.value, content: editor.value.getJSON(), done: resetDirty, fail: failSave })
}

async function editLink() {
  const current = editor.value.getAttributes('link').href || ''
  try {
    const { value } = await ElMessageBox.prompt('输入链接地址；留空可取消链接', '编辑链接', {
      inputValue: current, confirmButtonText: '应用', cancelButtonText: '取消',
    })
    const clean = value.trim()
    if (!clean) return editor.value.chain().focus().extendMarkRange('link').unsetLink().run()
    const href = /^(https?:\/\/|mailto:)/i.test(clean) ? clean : `https://${clean}`
    editor.value.chain().focus().extendMarkRange('link').setLink({ href }).run()
  } catch { /* cancelled */ }
}

function onEditorKeydown(event) {
  if (!editor.value || !actions.value.canSave) return
  if ((event.ctrlKey || event.metaKey) && event.key.toLocaleLowerCase() === 's') {
    event.preventDefault()
    if (dirty.value && !props.saving) save()
    return
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLocaleLowerCase() === 'k') {
    event.preventDefault()
    editLink()
    return
  }
  if (!slashOpen.value && event.key === '/' && !event.ctrlKey && !event.metaKey && !event.altKey) {
    const { $from } = editor.value.state.selection
    if ($from.parentOffset === 0) {
      slashOpen.value = true
      slashQuery.value = ''
      slashIndex.value = 0
      nextTick(() => updateSlashPosition(editor.value))
    }
    return
  }
  if (!slashOpen.value) return
  if (event.key === 'Escape') { event.preventDefault(); closeSlashMenu(); return }
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    const total = filteredCommands.value.length
    if (total) slashIndex.value = (slashIndex.value + (event.key === 'ArrowDown' ? 1 : -1) + total) % total
    return
  }
  if (event.key === 'Enter') {
    event.preventDefault()
    const command = filteredCommands.value[slashIndex.value]
    if (command) executeSlashCommand(command.id)
  }
}

function updateSlashQuery(instance) {
  if (!slashOpen.value) return
  const { $from } = instance.state.selection
  const before = $from.parent.textBetween(0, $from.parentOffset, undefined, '\ufffc')
  const slashAt = before.lastIndexOf('/')
  if (slashAt < 0) return closeSlashMenu()
  slashQuery.value = before.slice(slashAt + 1)
  slashRange.value = { from: $from.start() + slashAt, to: $from.pos }
  slashIndex.value = Math.min(slashIndex.value, Math.max(0, filteredCommands.value.length - 1))
  nextTick(() => updateSlashPosition(instance))
}

function updateSlashPosition(instance) {
  if (!instance || !slashOpen.value) return
  const coords = instance.view.coordsAtPos(instance.state.selection.from)
  slashPosition.value = {
    left: Math.max(12, Math.min(coords.left, window.innerWidth - 310)),
    top: coords.bottom + 8,
  }
}

function closeSlashMenu() {
  slashOpen.value = false
  slashQuery.value = ''
  slashRange.value = null
}

function executeSlashCommand(id) {
  if (slashRange.value) editor.value.chain().focus().deleteRange(slashRange.value).run()
  const chain = editor.value.chain().focus()
  if (id === 'paragraph') chain.setParagraph().run()
  else if (id.startsWith('heading-')) chain.setHeading({ level: Number(id.slice(-1)) }).run()
  else if (id === 'bullet-list') chain.toggleBulletList().run()
  else if (id === 'ordered-list') chain.toggleOrderedList().run()
  else if (id === 'task-list') chain.toggleTaskList().run()
  else if (id === 'blockquote') chain.toggleBlockquote().run()
  else if (id === 'code-block') chain.toggleCodeBlock().run()
  else if (id === 'horizontal-rule') chain.setHorizontalRule().run()
  else if (id === 'table') chain.insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()
  closeSlashMenu()
}

function navigateOutline(item) {
  const headings = canvas.value?.querySelectorAll('.tiptap h1, .tiptap h2, .tiptap h3, .tiptap h4, .tiptap h5, .tiptap h6')
  const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  headings?.[item.index]?.scrollIntoView({ block: 'start', behavior: reducedMotion ? 'auto' : 'smooth' })
}

watch(() => props.document, value => {
  title.value = value?.title || ''
  editor.value?.setEditable(Boolean(value && actions.value.canSave))
  editor.value?.commands.setContent(
    value?.content_json || { type: 'doc', content: [{ type: 'paragraph' }] },
    { emitUpdate: false },
  )
  dirty.value = false
  savedAt.value = null
  saveError.value = ''
  emit('dirty-change', false)
  closeSlashMenu()
  refreshDerivedState()
}, { immediate: true })

watch(actions, value => editor.value?.setEditable(Boolean(props.document && value.canSave)))
onBeforeUnmount(() => editor.value?.destroy())
</script>

<style scoped>
.editor-shell { display: flex; min-width: 0; min-height: 0; flex: 1; flex-direction: column; background: var(--surface-card, #fff); }
.editor-header { display: flex; flex-shrink: 0; align-items: flex-start; justify-content: space-between; gap: 24px; padding: 18px 24px 14px; border-bottom: 1px solid var(--border-color); }
.title-block { min-width: 0; flex: 1; }
.title-block h1 { margin: 0; color: var(--text-primary); font-size: 26px; }
.title-input :deep(.el-input__wrapper) { padding: 0; box-shadow: none !important; }
.title-input :deep(.el-input__inner) { height: 38px; color: var(--text-primary); font-size: 26px; font-weight: 700; }
.document-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-top: 8px; color: var(--text-muted-blue); font-size: 12px; }
.save-status.error { color: var(--color-danger); }
.header-actions { display: flex; flex-shrink: 0; gap: 8px; }
.editor-body { display: grid; min-width: 0; min-height: 0; flex: 1; grid-template-columns: minmax(0, 1fr) 190px; }
.canvas-wrap { position: relative; min-width: 0; min-height: 0; overflow: hidden; }
.document-canvas { height: 100%; overflow: auto; padding: 36px max(32px, calc((100% - 780px) / 2)); scroll-padding-top: 24px; }
.document-canvas :deep(.tiptap) { min-height: 480px; color: var(--text-primary); font-size: 16px; line-height: 1.8; outline: none; }
.document-canvas.is-empty :deep(.tiptap p:first-child)::before { float: left; height: 0; color: var(--text-muted-blue); content: '输入 / 插入标题、列表、表格等内容'; pointer-events: none; }
.document-canvas :deep(.tiptap h1) { margin: 1.5em 0 .55em; font-size: 30px; line-height: 1.3; }
.document-canvas :deep(.tiptap h2) { margin: 1.5em 0 .55em; font-size: 24px; line-height: 1.35; }
.document-canvas :deep(.tiptap h3) { margin: 1.4em 0 .5em; font-size: 20px; }
.document-canvas :deep(.tiptap h4) { margin: 1.35em 0 .45em; font-size: 17px; }
.document-canvas :deep(.tiptap h5), .document-canvas :deep(.tiptap h6) { margin: 1.3em 0 .4em; font-size: 16px; }
.document-canvas :deep(.tiptap blockquote) { margin: 1em 0; padding-left: 16px; border-left: 3px solid var(--color-primary); color: var(--text-secondary); }
.document-canvas :deep(.tiptap pre) { overflow: auto; padding: 14px 16px; border-radius: 9px; color: var(--surface-card); background: var(--sidebar-bg-to); font-family: Consolas, monospace; line-height: 1.55; }
.document-canvas :deep(.tiptap code:not(pre code)) { padding: 2px 5px; border-radius: 4px; color: var(--color-primary); background: var(--color-primary-light); }
.document-canvas :deep(.tiptap table) { width: 100%; margin: 1em 0; table-layout: fixed; border-collapse: collapse; }
.document-canvas :deep(.tiptap td), .document-canvas :deep(.tiptap th) { position: relative; min-width: 72px; padding: 8px; border: 1px solid var(--border-color); vertical-align: top; }
.document-canvas :deep(.tiptap th) { background: var(--surface-subtle, #fafbfe); font-weight: 700; }
.document-canvas :deep(.selectedCell::after) { position: absolute; inset: 0; background: var(--color-primary-light); content: ''; pointer-events: none; }
.document-canvas :deep(ul[data-type='taskList']) { padding-left: 0; list-style: none; }
.document-canvas :deep(ul[data-type='taskList'] li) { display: flex; gap: 8px; align-items: flex-start; }
.document-canvas :deep(ul[data-type='taskList'] label) { padding-top: 2px; }
.bubble-toolbar { display: flex; gap: 2px; padding: 5px; border: 1px solid var(--border-color); border-radius: 9px; background: var(--surface-card, #fff); box-shadow: 0 10px 28px rgba(26, 26, 46, .15); }
.bubble-toolbar button { min-width: 30px; height: 30px; padding: 0 7px; border: 0; border-radius: 6px; color: var(--text-secondary); background: transparent; cursor: pointer; }
.bubble-toolbar button.active { color: var(--color-primary); background: var(--color-primary-light); }
.empty-editor { display: grid; flex: 1; place-items: center; background: var(--surface-card, #fff); }
@media (hover: hover) and (pointer: fine) { .bubble-toolbar button:hover { color: var(--color-primary); background: var(--color-primary-light); } }
@media (max-width: 1100px) { .editor-body { grid-template-columns: minmax(0, 1fr); } .editor-body :deep(.editor-outline) { display: none; } }
@media (max-width: 900px) { .editor-header { flex-direction: column; padding: 16px 18px; } .document-canvas { padding: 24px 20px; } }
</style>
