import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  EDITOR_COMMANDS,
  extractOutline,
  filterEditorCommands,
  saveStatusLabel,
} from '../src/views/knowledge/components/editorConfig.js'
import {
  TEXT_COLOR_OPTIONS,
  TextColorMark,
  applyTextColor,
  normalizeTextColorTone,
} from '../src/views/knowledge/components/TextColorMark.js'
import { contentForKnowledgeSave, pendingImageCount } from '../src/views/knowledge/components/knowledgeImageState.js'

function read(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

test('semantic text colors expose one controlled palette and normalize unknown values', () => {
  assert.deepEqual(TEXT_COLOR_OPTIONS.map(item => item.tone), [null, 'gold', 'danger', 'success', 'info'])
  assert.deepEqual(TEXT_COLOR_OPTIONS.map(item => item.label), ['默认', '重点', '风险', '完成', '说明'])
  assert.equal(normalizeTextColorTone('gold'), 'gold')
  assert.equal(normalizeTextColorTone('#ff0000'), null)
  assert.equal(Object.isFrozen(TEXT_COLOR_OPTIONS), true)
  assert.equal(TEXT_COLOR_OPTIONS.every(Object.isFrozen), true)

  const parseRules = TextColorMark.config.parseHTML()
  assert.deepEqual(parseRules.map(rule => rule.tag), ['span[data-text-color]'])
  assert.deepEqual(parseRules[0].getAttrs({ getAttribute: () => 'success' }), { tone: 'success' })
  assert.equal(parseRules[0].getAttrs({ getAttribute: () => '#ff0000' }), false)
  assert.deepEqual(
    TextColorMark.config.renderHTML({ HTMLAttributes: { tone: 'danger' } }),
    ['span', { 'data-text-color': 'danger', class: 'knowledge-text-color knowledge-text-color--danger' }, 0],
  )
})

test('semantic text color commands set registered tones and clear the default tone', () => {
  function fakeEditor() {
    const calls = []
    const chain = {
      focus() { calls.push(['focus']); return chain },
      setMark(type, attrs) { calls.push(['setMark', type, attrs]); return chain },
      unsetMark(type) { calls.push(['unsetMark', type]); return chain },
      run() { calls.push(['run']); return true },
    }
    return { editor: { chain: () => chain }, calls }
  }

  const colored = fakeEditor()
  assert.equal(applyTextColor(colored.editor, 'gold'), true)
  assert.deepEqual(colored.calls, [['focus'], ['setMark', 'textColor', { tone: 'gold' }], ['run']])

  const cleared = fakeEditor()
  assert.equal(applyTextColor(cleared.editor, null), true)
  assert.deepEqual(cleared.calls, [['focus'], ['unsetMark', 'textColor'], ['run']])
})

test('knowledge image save content keeps only canonical image attributes', () => {
  const content = {
    type: 'doc',
    content: [{
      type: 'knowledgeImage',
      attrs: {
        assetId: 12,
        alt: '流程图',
        caption: '标准流程',
        uploadId: null,
        uploadStatus: null,
        uploadProgress: 100,
        uploadError: '',
      },
    }],
  }
  assert.equal(pendingImageCount(content), 0)
  assert.deepEqual(contentForKnowledgeSave(content), {
    type: 'doc',
    content: [{
      type: 'knowledgeImage',
      attrs: { assetId: 12, alt: '流程图', caption: '标准流程' },
    }],
  })
  assert.equal(pendingImageCount({
    type: 'doc',
    content: [{ type: 'knowledgeImage', attrs: { assetId: null } }],
  }), 1)
})

test('knowledge editor supports upload paste drop and blocks pending image saves', () => {
  const editor = read('../src/views/knowledge/components/KnowledgeEditor.vue')
  const toolbar = read('../src/views/knowledge/components/EditorToolbar.vue')
  const imageView = read('../src/views/knowledge/components/KnowledgeImageView.vue')

  assert.match(toolbar, /@mousedown\.prevent="\$emit\('insert-image'\)"/)
  assert.match(editor, /accept="image\/jpeg,image\/png,image\/webp"/)
  assert.match(editor, /@paste\.capture="onPaste"/)
  assert.match(editor, /@drop\.prevent="onDrop"/)
  assert.match(editor, /clipboardData\?\.items/)
  assert.match(editor, /pendingUploads\.value.*请等待图片上传完成/s)
  assert.match(editor, /deleteTemporaryKnowledgeImage\(asset\.data\.id\)/)
  assert.match(imageView, /getKnowledgeImageBlob\(expected\)/)
  assert.match(imageView, /URL\.revokeObjectURL/)
})

test('AI optimization UI is governed, asynchronous, and reviewer-confirmed', () => {
  const editor = read('../src/views/knowledge/components/KnowledgeEditor.vue')
  const drawer = read('../src/views/knowledge/components/AiOptimizationDrawer.vue')
  const settings = read('../src/views/knowledge/KnowledgeAiSettings.vue')
  const workbench = read('../src/views/knowledge/KnowledgeWorkbench.vue')
  const approvalDialog = read('../src/views/knowledge/components/KnowledgeApprovalDialog.vue')

  assert.match(editor, /auth\.hasPermission\('knowledge_ai:write'\)/)
  assert.match(drawer, /mode === 'format'/)
  assert.match(drawer, /createDocumentAiJob/)
  assert.match(drawer, /getDocumentAiJob/)
  assert.match(drawer, /listDocumentAiJobs/)
  assert.match(drawer, /applyDocumentAiJob/)
  assert.match(drawer, /KnowledgeDocumentPreview :content="document\.content_json"/)
  assert.match(drawer, /KnowledgeDocumentPreview :content="job\.result\.content_json"/)
  assert.match(settings, /format_prompt/)
  assert.match(settings, /enhance_prompt/)
  assert.match(settings, /source_library_ids/)
  assert.match(settings, /target_library_ids/)
  assert.match(workbench, /confirm_cross_library_sources: crossLibraryConfirmed/)
  assert.match(approvalDialog, /requires_cross_library_confirmation/)
})

test('text color picker is accessible, closes safely, and is wired into the toolbar', () => {
  const picker = read('../src/views/knowledge/components/TextColorPicker.vue')
  const toolbar = read('../src/views/knowledge/components/EditorToolbar.vue')

  assert.match(picker, /aria-haspopup="menu"/)
  assert.match(picker, /:aria-expanded="open"/)
  assert.match(picker, /role="menu"/)
  assert.match(picker, /role="menuitemradio"/)
  assert.match(picker, /:aria-checked="currentTone === option\.tone"/)
  assert.match(picker, /@click\.stop="toggle"/)
  assert.match(picker, /@click\.stop="select\(option\.tone\)"/)
  assert.match(picker, /document\.addEventListener\('pointerdown', handleOutside\)/)
  assert.match(picker, /document\.addEventListener\('keydown', handleKeydown\)/)
  assert.match(picker, /document\.removeEventListener\('pointerdown', handleOutside\)/)
  assert.match(picker, /document\.removeEventListener\('keydown', handleKeydown\)/)
  assert.match(picker, /transition:[^;}]*transform 120ms cubic-bezier\(\.23,1,\.32,1\)/)
  assert.match(picker, /prefers-reduced-motion:\s*reduce/)
  assert.match(toolbar, /import TextColorPicker from ['"]\.\/TextColorPicker\.vue['"]/)
  assert.match(toolbar, /<TextColorPicker :editor="editor" :version="version"\s*\/?>/)
})

test('knowledge editor registers and renders every semantic text color with design tokens', () => {
  const editor = read('../src/views/knowledge/components/KnowledgeEditor.vue')

  assert.match(editor, /import \{ TextColorMark \} from ['"]\.\/TextColorMark\.js['"]/)
  assert.match(editor, /extensions:\s*\[[\s\S]*?TextColorMark,[\s\S]*?\]/)
  assert.match(editor, /\.knowledge-text-color--gold[^}]*color:\s*var\(--color-primary\)/)
  assert.match(editor, /\.knowledge-text-color--danger[^}]*color:\s*var\(--color-danger-text\)/)
  assert.match(editor, /\.knowledge-text-color--success[^}]*color:\s*var\(--color-success-text\)/)
  assert.match(editor, /\.knowledge-text-color--info[^}]*color:\s*var\(--color-info-text\)/)
})

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
  assert.match(editor, /editorVersion\.value; return pendingImageCount/)
  assert.match(editor, /canEdit: props\.document\?\.can_edit !== false/)
  assert.match(workbench, /canWriteLibrary.*knowledge:write.*knowledge:admin/)
  assert.ok(workbench.indexOf('await loadTree()') < workbench.indexOf('payload.done()'))
  assert.match(workbench, /await nextTick\(\)[\s\S]*?document\.value\.revision_id = result\.id[\s\S]*?payload\.done\(\)/)
})

test('programmatic hydration and internal refresh never trigger the discard guard', () => {
  const editor = read('../src/views/knowledge/components/KnowledgeEditor.vue')
  const workbench = read('../src/views/knowledge/KnowledgeWorkbench.vue')
  assert.match(editor, /commands\.setContent\([\s\S]*?\{ emitUpdate: false \},?\s*\)/)
  assert.match(editor, /setEditable\(Boolean\(value && actions\.value\.canSave\), false\)/)
  assert.match(editor, /setEditable\(Boolean\(props\.document && value\.canSave\), false\)/)
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

test('knowledge sidebar keeps its footer reachable while content regions scroll independently', () => {
  const sidebar = read('../src/views/knowledge/components/KnowledgeSidebar.vue')
  assert.match(sidebar, /\.knowledge-sidebar\s*\{[^}]*overflow:\s*hidden;/s)
  assert.match(sidebar, /\.library-list\s*\{[^}]*overflow-y:\s*auto;/s)
  assert.match(sidebar, /\.tree-section\s*\{[^}]*min-height:\s*0;[^}]*overflow:\s*hidden;/s)
  assert.match(sidebar, /\.tree-section\s*:deep\(\.el-tree\)\s*\{[^}]*overflow-y:\s*auto;/s)
  assert.match(sidebar, /\.collapse-footer\s*\{[^}]*flex:\s*0 0 auto;/s)
})

test('balanced sidebar keeps the selected tree and compact editor density', () => {
  const sidebar = read('../src/views/knowledge/components/KnowledgeSidebar.vue')
  const editor = read('../src/views/knowledge/components/KnowledgeEditor.vue')
  const toolbar = read('../src/views/knowledge/components/EditorToolbar.vue')
  const workbench = read('../src/views/knowledge/KnowledgeWorkbench.vue')
  assert.match(sidebar, /v-if="selectedLibraryId && !collapsed" class="tree-section"/)
  assert.doesNotMatch(sidebar, /v-if="library\.id === selectedLibraryId" class="tree-section"/)
  assert.match(workbench, /grid-template-columns:\s*310px minmax\(0,\s*1fr\)/)
  assert.match(workbench, /\.workspace\.collapsed\s*\{\s*grid-template-columns:\s*54px minmax\(0,\s*1fr\)/)
  assert.match(editor, /font-size:\s*15px;\s*line-height:\s*1\.7/)
  assert.match(toolbar, /height:\s*30px/)
})

test('editor scroll viewport includes its padding inside the available height', () => {
  const editor = read('../src/views/knowledge/components/KnowledgeEditor.vue')

  assert.match(
    editor,
    /\.document-canvas\s*\{[^}]*box-sizing:\s*border-box;[^}]*height:\s*100%;[^}]*overflow:\s*auto;/s,
  )
})
