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
  assert.ok(workbench.indexOf('await Promise.all([loadTree(), selectDocument(document.value.id)])') < workbench.indexOf('payload.done()'))
  assert.match(workbench, /await nextTick\(\)\s+payload\.done\(\)/)
})
