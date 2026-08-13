<template>
  <EditorContent :editor="editor" class="knowledge-preview" />
</template>

<script setup>
import { onBeforeUnmount, watch } from 'vue'
import { EditorContent, useEditor } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import Link from '@tiptap/extension-link'
import { TaskItem, TaskList } from '@tiptap/extension-list'
import { Table } from '@tiptap/extension-table'
import TableRow from '@tiptap/extension-table-row'
import TableHeader from '@tiptap/extension-table-header'
import TableCell from '@tiptap/extension-table-cell'
import { ConfirmationMark } from './ConfirmationMark.js'
import { KnowledgeImage } from './KnowledgeImage.js'
import { TextColorMark } from './TextColorMark.js'

const props = defineProps({ content: { type: Object, required: true } })

const editor = useEditor({
  editable: false,
  extensions: [
    StarterKit.configure({ link: false, underline: false }),
    Link.configure({ openOnClick: true, protocols: ['http', 'https', 'mailto'] }),
    ConfirmationMark,
    TextColorMark,
    KnowledgeImage,
    TaskList,
    TaskItem.configure({ nested: true }),
    Table.configure({ resizable: false }),
    TableRow,
    TableHeader,
    TableCell,
  ],
  content: props.content,
})

watch(() => props.content, content => editor.value?.commands.setContent(content), { deep: true })
onBeforeUnmount(() => editor.value?.destroy())
</script>

<style scoped>
.knowledge-preview { max-height: 55vh; overflow: auto; padding: 22px; border: 1px solid var(--border-color); border-radius: var(--radius-lg, 12px); background: var(--surface-subtle); }
.knowledge-preview :deep(.tiptap) { color: var(--text-primary); font-size: 15px; line-height: 1.7; outline: none; }
.knowledge-preview :deep(.tiptap h1) { margin: 1.2em 0 .45em; font-size: 26px; }
.knowledge-preview :deep(.tiptap h2) { margin: 1.2em 0 .45em; font-size: 21px; }
.knowledge-preview :deep(.tiptap h3) { margin: 1.15em 0 .4em; font-size: 18px; }
.knowledge-preview :deep(.tiptap blockquote) { padding-left: 12px; border-left: 3px solid var(--color-primary); color: var(--text-secondary); }
.knowledge-preview :deep(.tiptap pre) { overflow: auto; padding: 10px 12px; border-radius: 9px; color: var(--surface-card); background: var(--sidebar-bg-to); }
.knowledge-preview :deep(.tiptap table) { width: 100%; table-layout: fixed; border-collapse: collapse; }
.knowledge-preview :deep(.tiptap td), .knowledge-preview :deep(.tiptap th) { padding: 6px; border: 1px solid var(--border-color); vertical-align: top; }
.knowledge-preview :deep(.tiptap th) { background: var(--surface-card); }
.knowledge-preview :deep([data-confirmation='true']) { color: var(--color-danger); font-weight: 700; }
.knowledge-preview :deep(.knowledge-text-color--gold) { color: var(--color-primary); }
.knowledge-preview :deep(.knowledge-text-color--danger) { color: var(--color-danger-text); }
.knowledge-preview :deep(.knowledge-text-color--success) { color: var(--color-success-text); }
.knowledge-preview :deep(.knowledge-text-color--info) { color: var(--color-info-text); }
</style>
