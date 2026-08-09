<template>
  <section v-if="document" class="editor-shell">
    <header class="editor-header">
      <div class="title-block">
        <el-input v-if="actions.canSave" v-model="title" class="title-input" maxlength="256" @input="markDirty" />
        <h1 v-else>{{ document.title }}</h1>
        <div class="document-meta">
          <el-tag effect="plain" :type="statusType">{{ statusLabel }}</el-tag>
          <span>版本 v{{ document.version_no || 1 }}</span>
          <span v-if="document.pending_approval_id">审批中仍可编辑，新内容不会改变待审版本</span>
        </div>
      </div>
      <div class="header-actions">
        <GlassButton v-if="actions.canSave" variant="ghost" :loading="saving" @click="save">保存草稿</GlassButton>
        <GlassButton v-if="actions.canSubmit" variant="primary" :disabled="dirty" @click="$emit('submit')">提交审批</GlassButton>
      </div>
    </header>

    <div v-if="editor && actions.canSave" class="toolbar" aria-label="文档格式工具栏">
      <button type="button" :class="{ active: editor.isActive('bold') }" title="加粗" @click="editor.chain().focus().toggleBold().run()"><strong>B</strong></button>
      <button type="button" :class="{ active: editor.isActive('italic') }" title="斜体" @click="editor.chain().focus().toggleItalic().run()"><em>I</em></button>
      <button type="button" :class="{ active: editor.isActive('heading', { level: 2 }) }" title="二级标题" @click="editor.chain().focus().toggleHeading({ level: 2 }).run()">H2</button>
      <button type="button" :class="{ active: editor.isActive('bulletList') }" title="无序列表" @click="editor.chain().focus().toggleBulletList().run()">• 列表</button>
      <button type="button" :class="{ active: editor.isActive('blockquote') }" title="引用" @click="editor.chain().focus().toggleBlockquote().run()">引用</button>
      <button type="button" title="撤销" :disabled="!editor.can().undo()" @click="editor.chain().focus().undo().run()">撤销</button>
      <button type="button" title="重做" :disabled="!editor.can().redo()" @click="editor.chain().focus().redo().run()">重做</button>
    </div>
    <EditorContent :editor="editor" class="document-canvas" />
  </section>

  <section v-else class="empty-editor">
    <el-empty description="从左侧选择文档开始阅读" :image-size="120" />
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { EditorContent, useEditor } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import Link from '@tiptap/extension-link'
import { Table } from '@tiptap/extension-table'
import TableRow from '@tiptap/extension-table-row'
import TableHeader from '@tiptap/extension-table-header'
import TableCell from '@tiptap/extension-table-cell'
import { documentActions } from '../knowledgeState.js'

const props = defineProps({ document: { type: Object, default: null }, role: { type: String, default: 'viewer' }, saving: Boolean })
const emit = defineEmits(['save', 'submit', 'dirty-change'])
const title = ref('')
const dirty = ref(false)
const actions = computed(() => documentActions({ role: props.role, status: props.document?.status, pendingApprovalId: props.document?.pending_approval_id }))
const statusLabel = computed(() => ({ draft: '草稿', pending: '待审批', published: '已发布' }[props.document?.status] || props.document?.status))
const statusType = computed(() => ({ draft: 'info', pending: 'warning', published: 'success' }[props.document?.status] || 'info'))

const editor = useEditor({
  editable: false,
  extensions: [
    StarterKit.configure({ link: false }),
    Link.configure({ openOnClick: false, protocols: ['http', 'https', 'mailto'] }),
    Table.configure({ resizable: false }), TableRow, TableHeader, TableCell,
  ],
  content: { type: 'doc', content: [{ type: 'paragraph' }] },
  onUpdate: markDirty,
})

function markDirty() {
  if (!dirty.value) {
    dirty.value = true
    emit('dirty-change', true)
  }
}

function resetDirty() {
  dirty.value = false
  emit('dirty-change', false)
}

function save() {
  emit('save', { title: title.value, content: editor.value.getJSON(), done: resetDirty })
}

watch(() => props.document, value => {
  title.value = value?.title || ''
  editor.value?.setEditable(Boolean(value && actions.value.canSave))
  editor.value?.commands.setContent(value?.content_json || { type: 'doc', content: [{ type: 'paragraph' }] }, false)
  resetDirty()
}, { immediate: true })

watch(actions, value => editor.value?.setEditable(Boolean(props.document && value.canSave)))
onBeforeUnmount(() => editor.value?.destroy())
</script>

<style scoped>
.editor-shell { display: flex; min-width: 0; min-height: 0; flex: 1; flex-direction: column; background: var(--surface-card, #fff); }
.editor-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; padding: 22px 28px 16px; border-bottom: 1px solid var(--border-color); }
.title-block { min-width: 0; flex: 1; }
.title-block h1 { margin: 0; color: var(--text-primary); font-size: 26px; }
.title-input :deep(.el-input__wrapper) { padding: 0; box-shadow: none !important; }
.title-input :deep(.el-input__inner) { height: 38px; color: var(--text-primary); font-size: 26px; font-weight: 700; }
.document-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-top: 10px; color: var(--text-muted-blue); font-size: 12px; }
.header-actions { display: flex; flex-shrink: 0; gap: 8px; }
.toolbar { display: flex; flex-wrap: wrap; gap: 4px; padding: 9px 28px; border-bottom: 1px solid var(--border-color); background: var(--surface-subtle, #fafafa); }
.toolbar button { min-width: 34px; height: 30px; padding: 0 9px; border: 1px solid transparent; border-radius: 6px; color: var(--text-secondary); background: transparent; cursor: pointer; }
.toolbar button.active { border-color: var(--color-primary); color: var(--color-primary); background: var(--color-primary-light); }
.toolbar button:disabled { opacity: .4; cursor: not-allowed; }
.toolbar button:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 1px; }
.document-canvas { min-height: 0; flex: 1; overflow: auto; padding: 36px max(32px, calc((100% - 780px) / 2)); }
.document-canvas :deep(.tiptap) { min-height: 480px; color: var(--text-primary); font-size: 16px; line-height: 1.8; outline: none; }
.document-canvas :deep(.tiptap h2) { margin: 1.6em 0 .6em; font-size: 22px; }
.document-canvas :deep(.tiptap blockquote) { margin: 1em 0; padding-left: 16px; border-left: 3px solid var(--color-primary); color: var(--text-secondary); }
.document-canvas :deep(.tiptap table) { width: 100%; border-collapse: collapse; }
.document-canvas :deep(.tiptap td), .document-canvas :deep(.tiptap th) { padding: 8px; border: 1px solid var(--border-color); }
.empty-editor { display: grid; flex: 1; place-items: center; background: var(--surface-card, #fff); }
@media (max-width: 900px) { .editor-header { flex-direction: column; padding: 18px; } .document-canvas { padding: 24px 20px; } }
</style>
