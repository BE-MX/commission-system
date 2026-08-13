<template>
  <section v-if="document" class="editor-shell">
    <header class="editor-header">
      <div class="title-block">
        <el-input v-if="actions.canSave" v-model="title" class="title-input" maxlength="256" @input="markDirty" />
        <h1 v-else>{{ document.title }}</h1>
        <div class="document-meta">
          <el-tag effect="plain" :type="statusType">{{ statusLabel }}</el-tag>
          <span>版本 v{{ document.version_no || 1 }}</span>
          <span class="save-status" :class="{ error: saveError }"><i class="save-dot" :class="saveTone" />{{ saveLabel }}</span>
          <span v-if="document.pending_approval_id">审批中仍可编辑，新内容不会改变待审版本</span>
        </div>
      </div>
      <div class="header-actions">
        <GlassButton v-if="actions.canSave && canUseAi" variant="secondary" left-icon="MagicStick" @click="aiDrawer = true">AI 优化</GlassButton>
        <GlassButton v-if="actions.canDelete" class="delete-action" variant="ghost" left-icon="Delete" @click="$emit('delete', document)">删除</GlassButton>
        <GlassButton v-if="actions.canSave" variant="ghost" :loading="saving" :disabled="!dirty || saving || pendingUploads" @click="save">保存草稿</GlassButton>
        <GlassButton v-if="actions.canSubmit" variant="primary" :disabled="dirty" @click="requestSubmit">提交审批</GlassButton>
      </div>
    </header>

    <EditorToolbar v-if="editor && actions.canSave" :editor="editor" :version="editorVersion" @edit-link="editLink" @insert-image="selectImage" />
    <input ref="imageInput" class="sr-only" type="file" accept="image/jpeg,image/png,image/webp" @change="onImageSelected" />
    <div class="editor-body">
      <div
        ref="canvas"
        class="canvas-wrap"
        @keydown.capture="onEditorKeydown"
        @paste.capture="onPaste"
        @dragover.prevent
        @drop.prevent="onDrop"
        @knowledge-image-retry="selectImage"
      >
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
    <AiOptimizationDrawer
      v-model="aiDrawer"
      :document="document"
      :dirty="dirty"
      @applied="$emit('ai-applied', $event)"
    />
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
import { ConfirmationMark } from './ConfirmationMark.js'
import { TextColorMark } from './TextColorMark.js'
import { KnowledgeImage } from './KnowledgeImage.js'
import { contentForKnowledgeSave, pendingImageCount } from './knowledgeImageState.js'
import { deleteTemporaryKnowledgeImage, uploadKnowledgeImage } from '@/api/knowledge'
import { msgError } from '@/utils/feedback'
import { useAuthStore } from '@/stores/auth'
import AiOptimizationDrawer from './AiOptimizationDrawer.vue'
import { EDITOR_COMMANDS, extractOutline, filterEditorCommands, saveStatusLabel } from './editorConfig.js'
const props = defineProps({ document: { type: Object, default: null }, role: { type: String, default: 'viewer' }, saving: Boolean })
const emit = defineEmits(['save', 'submit', 'dirty-change', 'delete', 'ai-applied'])
const auth = useAuthStore()
const canvas = ref(null)
const imageInput = ref(null)
const aiDrawer = ref(false)
const title = ref('')
const dirty = ref(false)
const changeVersion = ref(0)
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
const saveTone = computed(() => {
  if (saveError.value) return 'error'
  if (props.saving) return 'saving'
  if (dirty.value) return 'dirty'
  return 'saved'
})
const filteredCommands = computed(() => filterEditorCommands(EDITOR_COMMANDS, slashQuery.value))
const pendingUploads = computed(() => pendingImageCount(editor.value?.getJSON() || {}))
const canUseAi = computed(() => auth.hasPermission('knowledge_ai:write') || auth.hasPermission('knowledge_ai:admin'))
const editor = useEditor({
  editable: false,
  extensions: [
    StarterKit.configure({ link: false, underline: false }),
    Link.configure({ openOnClick: false, protocols: ['http', 'https', 'mailto'] }),
    ConfirmationMark,
    TextColorMark,
    KnowledgeImage,
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
  changeVersion.value += 1
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
  if (pendingUploads.value) return msgError('请等待图片上传完成，或移除失败的图片')
  const savedVersion = changeVersion.value
  emit('save', {
    title: title.value,
    content: contentForKnowledgeSave(editor.value.getJSON()),
    done: () => { if (savedVersion === changeVersion.value) resetDirty() },
    fail: () => { if (savedVersion === changeVersion.value) failSave() },
  })
}

function missingImageAltCount() {
  let count = 0
  editor.value?.state.doc.descendants(node => {
    if (node.type.name === 'knowledgeImage' && !String(node.attrs.alt || '').trim()) count += 1
  })
  return count
}

async function requestSubmit() {
  const missing = missingImageAltCount()
  if (missing) {
    try {
      await ElMessageBox.confirm(
        `当前有 ${missing} 张图片未填写替代文本，这会影响检索和无障碍阅读。仍要提交吗？`,
        '图片说明提醒',
        { confirmButtonText: '仍然提交', cancelButtonText: '返回补充', type: 'warning' },
      )
    } catch { return }
  }
  emit('submit')
}

function selectImage() {
  imageInput.value?.click()
}

function onImageSelected(event) {
  const files = [...(event.target.files || [])]
  event.target.value = ''
  if (files.length) insertImageFiles(files)
}

function supportedImageFiles(files) {
  const allowed = new Set(['image/jpeg', 'image/png', 'image/webp'])
  return files.filter(file => file instanceof File && allowed.has(file.type))
}

function onPaste(event) {
  if (!actions.value.canSave) return
  const directFiles = [...(event.clipboardData?.files || [])]
  const itemFiles = [...(event.clipboardData?.items || [])]
    .filter(item => item.kind === 'file')
    .map(item => item.getAsFile())
    .filter(Boolean)
  const images = supportedImageFiles(directFiles.length ? directFiles : itemFiles)
  if (!images.length) return
  event.preventDefault()
  insertImageFiles(images)
}

function onDrop(event) {
  if (!actions.value.canSave) return
  const images = supportedImageFiles([...(event.dataTransfer?.files || [])])
  if (!images.length) return
  const coords = editor.value.view.posAtCoords({ left: event.clientX, top: event.clientY })
  if (coords) editor.value.commands.setTextSelection(coords.pos)
  insertImageFiles(images)
}

function findUploadPosition(uploadId) {
  let result = null
  editor.value?.state.doc.descendants((node, pos) => {
    if (node.type.name === 'knowledgeImage' && node.attrs.uploadId === uploadId) {
      result = pos
      return false
    }
    return result === null
  })
  return result
}

async function insertImageFiles(files) {
  for (const file of files) {
    const uploadId = crypto.randomUUID()
    editor.value.chain().focus().insertContent({
      type: 'knowledgeImage',
      attrs: {
        assetId: null,
        alt: '',
        caption: '',
        uploadId,
        uploadStatus: 'uploading',
        uploadProgress: 0,
        uploadError: '',
      },
    }).run()
    try {
      const asset = await uploadKnowledgeImage(
        props.document.library_id,
        file,
        progress => {
          const pos = findUploadPosition(uploadId)
          if (pos === null) return
          editor.value.commands.command(({ tr }) => {
            tr.setNodeMarkup(pos, undefined, {
              ...tr.doc.nodeAt(pos).attrs,
              uploadProgress: progress,
            })
            return true
          })
        },
      )
      const pos = findUploadPosition(uploadId)
      if (pos === null) {
        await deleteTemporaryKnowledgeImage(asset.data.id).catch(() => {})
        continue
      }
      editor.value.commands.command(({ tr }) => {
        tr.setNodeMarkup(pos, undefined, {
          assetId: asset.data.id,
          alt: '',
          caption: '',
          uploadId: null,
          uploadStatus: null,
          uploadProgress: 100,
          uploadError: '',
        })
        return true
      })
    } catch (error) {
      const pos = findUploadPosition(uploadId)
      if (pos !== null) {
        editor.value.commands.command(({ tr }) => {
          tr.setNodeMarkup(pos, undefined, {
            ...tr.doc.nodeAt(pos).attrs,
            uploadStatus: 'error',
            uploadError: error?.response?.data?.detail || '上传失败，请移除后重试',
          })
          return true
        })
      }
    }
  }
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
  aiDrawer.value = false
}

function navigateOutline(item) {
  const headings = canvas.value?.querySelectorAll('.tiptap h1, .tiptap h2, .tiptap h3, .tiptap h4, .tiptap h5, .tiptap h6')
  const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  headings?.[item.index]?.scrollIntoView({ block: 'start', behavior: reducedMotion ? 'auto' : 'smooth' })
}

watch(() => props.document, value => {
  changeVersion.value += 1
  title.value = value?.title || ''
  editor.value?.setEditable(Boolean(value && actions.value.canSave), false)
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

watch(actions, value => editor.value?.setEditable(Boolean(props.document && value.canSave), false))
onBeforeUnmount(() => editor.value?.destroy())
</script>

<style scoped>
.editor-shell { display: flex; min-width: 0; min-height: 0; flex: 1; flex-direction: column; background: var(--surface-card, #fff); }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0, 0, 0, 0); }
.editor-header { display: flex; flex-shrink: 0; align-items: flex-start; justify-content: space-between; gap: 16px; padding: 12px 18px 10px; border-bottom: 1px solid var(--border-color); }
.title-block { min-width: 0; flex: 1; }
.title-block h1 { margin: 0; color: var(--text-primary); font-size: 22px; }
.title-input :deep(.el-input__wrapper) { padding: 0; box-shadow: 0 1px 0 0 transparent !important; transition: box-shadow .25s var(--ease-out-strong, ease-out); }
.title-input :deep(.el-input__wrapper.is-focus) { box-shadow: 0 2px 0 0 var(--color-primary) !important; }
.title-input :deep(.el-input__inner) { height: 32px; color: var(--text-primary); font-size: 22px; font-weight: 700; }
.document-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 4px; color: var(--text-muted-blue); font-size: 11.5px; }
.save-status { display: inline-flex; align-items: center; gap: 6px; transition: color .2s ease; }
.save-status.error { color: var(--color-danger); }
.save-dot { width: 6px; height: 6px; flex: 0 0 auto; border-radius: 50%; background: var(--text-muted); transition: background-color .25s ease; }
.save-dot.dirty { background: var(--color-gold-muted); }
.save-dot.saving { background: var(--color-primary); animation: dot-blink 1s ease-in-out infinite; }
.save-dot.saved { background: var(--color-success); }
.save-dot.error { background: var(--color-danger); }
.header-actions { display: flex; flex-shrink: 0; gap: 6px; }
.delete-action { color: var(--color-danger); }
.editor-body { display: grid; min-width: 0; min-height: 0; flex: 1; grid-template-columns: minmax(0, 1fr) 170px; }
.canvas-wrap { position: relative; min-width: 0; min-height: 0; overflow: hidden; }
.document-canvas { box-sizing: border-box; height: 100%; overflow: auto; padding: 24px max(24px, calc((100% - 840px) / 2)); scroll-padding-top: 18px; }
.document-canvas :deep(.tiptap) { min-height: 420px; color: var(--text-primary); font-size: 15px; line-height: 1.7; outline: none; }
.document-canvas.is-empty :deep(.tiptap p:first-child)::before { float: left; height: 0; color: var(--text-muted-blue); content: '输入 / 插入标题、列表、表格等内容'; pointer-events: none; }
.document-canvas :deep(.tiptap h1) { margin: 1.25em 0 .45em; font-size: 26px; line-height: 1.3; }
.document-canvas :deep(.tiptap h2) { margin: 1.25em 0 .45em; font-size: 21px; line-height: 1.35; }
.document-canvas :deep(.tiptap h3) { margin: 1.2em 0 .4em; font-size: 18px; }
.document-canvas :deep(.tiptap h4) { margin: 1.15em 0 .4em; font-size: 16px; }
.document-canvas :deep(.tiptap h5), .document-canvas :deep(.tiptap h6) { margin: 1.1em 0 .35em; font-size: 15px; }
.document-canvas :deep(.tiptap blockquote) { margin: .8em 0; padding-left: 12px; border-left: 3px solid var(--color-primary); color: var(--text-secondary); }
.document-canvas :deep(.tiptap pre) { overflow: auto; padding: 10px 12px; border-radius: 9px; color: var(--surface-card); background: var(--sidebar-bg-to); font-family: Consolas, monospace; line-height: 1.5; }
.document-canvas :deep(.tiptap code:not(pre code)) { padding: 2px 5px; border-radius: 4px; color: var(--color-primary); background: var(--color-primary-light); }
.document-canvas :deep([data-confirmation='true']) { color: var(--color-danger); font-weight: 700; }
.document-canvas :deep(.knowledge-text-color--gold) { color: var(--color-primary); }
.document-canvas :deep(.knowledge-text-color--danger) { color: var(--color-danger-text); }
.document-canvas :deep(.knowledge-text-color--success) { color: var(--color-success-text); }
.document-canvas :deep(.knowledge-text-color--info) { color: var(--color-info-text); }
.document-canvas :deep(.tiptap table) { width: 100%; margin: 1em 0; table-layout: fixed; border-collapse: collapse; }
.document-canvas :deep(.tiptap td), .document-canvas :deep(.tiptap th) { position: relative; min-width: 72px; padding: 6px; border: 1px solid var(--border-color); vertical-align: top; }
.document-canvas :deep(.tiptap th) { background: var(--surface-subtle, #fafbfe); font-weight: 700; }
.document-canvas :deep(.selectedCell::after) { position: absolute; inset: 0; background: var(--color-primary-light); content: ''; pointer-events: none; }
.document-canvas :deep(ul[data-type='taskList']) { padding-left: 0; list-style: none; }
.document-canvas :deep(ul[data-type='taskList'] li) { display: flex; gap: 8px; align-items: flex-start; }
.document-canvas :deep(ul[data-type='taskList'] label) { padding-top: 2px; }
.bubble-toolbar { display: flex; gap: 2px; padding: 5px; border: 1px solid var(--border-color); border-radius: 9px; background: var(--surface-card, #fff); box-shadow: 0 10px 28px rgba(26, 26, 46, .15); }
.bubble-toolbar button { min-width: 30px; height: 30px; padding: 0 7px; border: 0; border-radius: 6px; color: var(--text-secondary); background: transparent; cursor: pointer; transition: color .12s ease, background-color .12s ease, transform .12s var(--ease-out-strong, ease-out); }
.bubble-toolbar button:active { transform: scale(.92); }
.bubble-toolbar button.active { color: var(--color-primary); background: var(--color-primary-light); }
.empty-editor { display: grid; flex: 1; place-items: center; background: var(--surface-card, #fff); }
@keyframes dot-blink { 0%, 100% { opacity: 1; } 50% { opacity: .35; } }
@media (hover: hover) and (pointer: fine) { .bubble-toolbar button:hover { color: var(--color-primary); background: var(--color-primary-light); } }
@media (max-width: 1100px) { .editor-body { grid-template-columns: minmax(0, 1fr); } .editor-body :deep(.editor-outline) { display: none; } }
@media (max-width: 900px) { .editor-header { flex-direction: column; padding: 12px 14px; } .document-canvas { padding: 18px 16px; } }
@media (prefers-reduced-motion: reduce) {
  .save-dot.saving { animation: none; }
  .title-input :deep(.el-input__wrapper), .save-status, .save-dot, .bubble-toolbar button { transition: none; }
}
</style>
