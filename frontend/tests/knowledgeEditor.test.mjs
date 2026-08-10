import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  EDITOR_COMMANDS,
  extractOutline,
  filterEditorCommands,
  saveStatusLabel,
} from '../src/views/knowledge/components/editorConfig.js'

function read(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

test('slash commands cover supported P0 blocks and filter by Chinese or English terms', () => {
  const ids = EDITOR_COMMANDS.map(item => item.id)
  for (const id of ['paragraph', 'heading-1', 'heading-6', 'bullet-list', 'ordered-list', 'task-list', 'blockquote', 'code-block', 'horizontal-rule', 'table']) {
    assert.ok(ids.includes(id), `missing command ${id}`)
  }
  assert.deepEqual(filterEditorCommands(EDITOR_COMMANDS, '表格').map(item => item.id), ['table'])
  assert.deepEqual(filterEditorCommands(EDITOR_COMMANDS, 'code').map(item => item.id), ['code-block'])
  assert.equal(filterEditorCommands(EDITOR_COMMANDS, '不存在').length, 0)
})

test('outline extracts nested heading text in document order and ignores empty headings', () => {
  const content = {
    type: 'doc',
    content: [
      { type: 'heading', attrs: { level: 2 }, content: [{ type: 'text', text: '权限模型' }] },
      { type: 'paragraph', content: [{ type: 'text', text: '正文' }] },
      { type: 'heading', attrs: { level: 3 }, content: [{ type: 'text', text: '角色' }, { type: 'text', text: '矩阵' }] },
      { type: 'heading', attrs: { level: 4 } },
    ],
  }
  assert.deepEqual(extractOutline(content), [
    { id: 'heading-0', level: 2, text: '权限模型', index: 0 },
    { id: 'heading-1', level: 3, text: '角色矩阵', index: 1 },
  ])
})

test('save status gives actionable feedback for dirty, saving, saved, and failed states', () => {
  assert.equal(saveStatusLabel({ dirty: true }), '有未保存修改')
  assert.equal(saveStatusLabel({ dirty: true, saving: true }), '正在保存…')
  assert.equal(saveStatusLabel({ error: '网络错误' }), '保存失败，请重试')
  assert.equal(saveStatusLabel({ savedAt: new Date('2026-08-10T01:02:00Z') }, { locale: 'zh-CN', timeZone: 'Asia/Shanghai' }), '已保存 09:02')
  assert.equal(saveStatusLabel({}), '已保存')
})

test('editor shell exposes accessible P0 interaction surfaces', () => {
  const editor = read('../src/views/knowledge/components/KnowledgeEditor.vue')
  const toolbar = read('../src/views/knowledge/components/EditorToolbar.vue')
  const outline = read('../src/views/knowledge/components/EditorOutline.vue')
  const workbench = read('../src/views/knowledge/KnowledgeWorkbench.vue')
  assert.match(editor, /EditorToolbar/)
  assert.match(editor, /EditorSlashMenu/)
  assert.match(editor, /EditorOutline/)
  assert.match(toolbar, /aria-label="文档格式工具栏"/)
  assert.match(outline, /aria-label="文档大纲"/)
  assert.match(editor, /@keydown\.capture="onEditorKeydown"/)
  assert.match(editor, /event\.key\.toLocaleLowerCase\(\) === 's'/)
  assert.match(editor, /event\.key\.toLocaleLowerCase\(\) === 'k'/)
  assert.match(editor, /window\.innerWidth - 310/)
  assert.match(editor, /prefers-reduced-motion: reduce/)
  assert.ok(workbench.indexOf('await Promise.all([loadTree(), reloadDocument(document.value.id)])') < workbench.indexOf('payload.done()'))
  assert.match(workbench, /await nextTick\(\)\s+payload\.done\(\)/)
})

test('programmatic hydration and internal refresh never trigger the discard guard', () => {
  const editor = read('../src/views/knowledge/components/KnowledgeEditor.vue')
  const workbench = read('../src/views/knowledge/KnowledgeWorkbench.vue')
  assert.match(editor, /commands\.setContent\([\s\S]*?\{ emitUpdate: false \},?\s*\)/)
  assert.match(workbench, /async function reloadDocument\(id\)[\s\S]*?knowledgeClient\.get\(`\/documents\/\$\{id\}`\)/)
  assert.match(workbench, /async function selectDocument\(id\)\s*\{\s*if \(document\.value\?\.id === id\) return\s*if \(!\(await allowDiscard\(\)\)\) return\s*await reloadDocument\(id\)/)
  const saveBody = workbench.slice(workbench.indexOf('async function saveDocument'), workbench.indexOf('async function submitDocument'))
  assert.match(saveBody, /const targetId = document\.value\.id/)
  assert.match(saveBody, /put\(`\/documents\/\$\{targetId\}`/)
  assert.match(saveBody, /document\.value\.version_no = result\.version_no/)
  assert.doesNotMatch(saveBody, /reloadDocument\(/)
  assert.doesNotMatch(saveBody, /selectDocument\(/)
  const submitBody = workbench.slice(workbench.indexOf('async function submitDocument'), workbench.indexOf('async function openMembers'))
  assert.match(submitBody, /const targetId = document\.value\.id/)
  assert.match(submitBody, /document\.value\?\.id === targetId && !dirty\.value/)
  assert.match(workbench, /async function selectLibrary\(id\)\s*\{\s*if \(selectedLibraryId\.value === id\) return true\s*if \(!\(await allowDiscard\(\)\)\) return false/)
  const searchBody = workbench.slice(workbench.indexOf('async function openSearchResult'), workbench.indexOf('async function allowDiscard'))
  assert.match(searchBody, /if \(library && !\(await selectLibrary\(library\.id\)\)\) return/)
  const approveBody = workbench.slice(workbench.indexOf('async function approve'), workbench.indexOf('async function reject'))
  assert.match(approveBody, /document\.value\?\.id === item\.document_id && !dirty\.value/)
  assert.match(editor, /const savedVersion = changeVersion\.value/)
  assert.match(editor, /savedVersion === changeVersion\.value/)
  assert.match(editor, /changeVersion\.value \+= 1/)
})

test('delete controls are role-gated and do not trigger selection clicks', () => {
  const sidebar = read('../src/views/knowledge/components/KnowledgeSidebar.vue')
  const editor = read('../src/views/knowledge/components/KnowledgeEditor.vue')
  const workbench = read('../src/views/knowledge/KnowledgeWorkbench.vue')
  assert.match(sidebar, /canDeleteLibrary/)
  assert.match(sidebar, /@click\.stop="\$emit\('delete-library', library\)"/)
  assert.match(sidebar, /@click\.stop="\$emit\('delete-node', data\)"/)
  assert.match(editor, /actions\.canDelete/)
  assert.match(editor, /\$emit\('delete', document\)/)
  assert.match(workbench, /@delete-library="deleteLibrary"/)
  assert.match(workbench, /@delete-node="deleteNode"/)
  assert.match(workbench, /knowledgeClient\.delete\(`\/libraries\/\$\{library\.id\}`\)/)
  assert.match(workbench, /knowledgeClient\.delete\(`\/documents\/\$\{node\.id\}`\)/)
})

test('knowledge sidebar scrolls when libraries and directory nodes exceed its height', () => {
  const sidebar = read('../src/views/knowledge/components/KnowledgeSidebar.vue')
  assert.match(sidebar, /\.knowledge-sidebar\s*\{[^}]*overflow-y:\s*auto;/s)
})
