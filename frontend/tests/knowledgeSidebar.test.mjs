import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  LIBRARY_CATEGORIES,
  SIDEBAR_COLLAPSED_KEY,
  isDuplicateMember,
  isTextOverflowing,
  overflowTooltipVisible,
  readSidebarCollapsed,
  writeSidebarCollapsed,
} from '../src/views/knowledge/knowledgeUi.js'


test('library categories expose the exact label and tone contract', () => {
  assert.deepEqual(Object.keys(LIBRARY_CATEGORIES), ['company', 'department', 'personal'])
  assert.deepEqual(LIBRARY_CATEGORIES, {
    company: { label: '公司级', tone: 'company' },
    department: { label: '部门级', tone: 'department' },
    personal: { label: '个人级', tone: 'personal' },
  })
  assert.equal(Object.isFrozen(LIBRARY_CATEGORIES), true)
  assert.equal(Object.values(LIBRARY_CATEGORIES).every(Object.isFrozen), true)
})


test('sidebar collapsed storage accepts only the explicit true string', () => {
  const values = new Map()
  const storage = {
    getItem: key => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(key, value),
  }

  assert.equal(readSidebarCollapsed(storage), false)

  values.set(SIDEBAR_COLLAPSED_KEY, 'false')
  assert.equal(readSidebarCollapsed(storage), false)

  values.set(SIDEBAR_COLLAPSED_KEY, 'broken')
  assert.equal(readSidebarCollapsed(storage), false)

  values.set(SIDEBAR_COLLAPSED_KEY, 'true')
  assert.equal(readSidebarCollapsed(storage), true)

  writeSidebarCollapsed(true, storage)
  assert.equal(values.get(SIDEBAR_COLLAPSED_KEY), 'true')

  writeSidebarCollapsed(false, storage)
  assert.equal(values.get(SIDEBAR_COLLAPSED_KEY), 'false')

  writeSidebarCollapsed('false', storage)
  assert.equal(values.get(SIDEBAR_COLLAPSED_KEY), 'false')
})


test('sidebar storage failures are ignored', () => {
  const readFailure = {
    getItem: () => { throw new Error('storage unavailable') },
  }
  const writeFailure = {
    setItem: () => { throw new Error('storage unavailable') },
  }

  assert.equal(readSidebarCollapsed(readFailure), false)
  assert.doesNotThrow(() => writeSidebarCollapsed(true, writeFailure))
})


test('duplicate members match stable user ids with strict equality', () => {
  const members = [{ user_id: 7 }]

  assert.equal(isDuplicateMember(members, 7), true)
  assert.equal(isDuplicateMember(members, 8), false)
  assert.equal(isDuplicateMember(members, '7'), false)
})


test('text overflow detection compares rendered widths', () => {
  assert.equal(isTextOverflowing(null), false)
  assert.equal(isTextOverflowing({ scrollWidth: 100, clientWidth: 100 }), false)
  assert.equal(isTextOverflowing({ scrollWidth: 101, clientWidth: 100 }), true)
})


test('overflow tooltip visibility follows hover and focus state', () => {
  const state = { overflowing: false, hovering: true, focused: true }
  assert.equal(overflowTooltipVisible(state), false)

  state.overflowing = true
  state.hovering = false
  state.focused = false
  assert.equal(overflowTooltipVisible(state), false)

  state.hovering = true
  assert.equal(overflowTooltipVisible(state), true)

  state.hovering = false
  assert.equal(overflowTooltipVisible(state), false)

  state.focused = true
  assert.equal(overflowTooltipVisible(state), true)

  state.focused = false
  assert.equal(overflowTooltipVisible(state), false)
})


test('overflow tooltip enables itself only when the rendered text overflows', () => {
  const source = readFileSync(
    new URL('../src/views/knowledge/components/OverflowTooltip.vue', import.meta.url),
    'utf8',
  )

  assert.match(source, /import\s*\{\s*isTextOverflowing,\s*overflowTooltipVisible\s*\}\s*from\s*['"]\.\.\/knowledgeUi\.js['"]/)
  assert.match(source, /overflowing\.value\s*=\s*isTextOverflowing\(element\)/)
  assert.match(source, /const tooltipVisible\s*=\s*computed\(\(\) => overflowTooltipVisible\(\{/)
  assert.match(source, /resizeObserver\s*=\s*new ResizeObserver\(measure\)/)
  assert.match(source, /resizeObserver\.observe\(element\)/)
  assert.match(source, /watch\(\(\) => props\.text,\s*\(\) => nextTick\(measure\)\)/)
  assert.match(source, /resizeObserver\?\.disconnect\(\)/)
  assert.match(source, /:disabled="!overflowing"/)
  assert.match(source, /:visible="tooltipVisible"/)
  assert.match(source, /focusable:\s*\{ type:\s*Boolean,\s*default:\s*true \}/)
  assert.match(source, /:tabindex="focusable && overflowing \? 0 : undefined"/)
  assert.match(source, /@mouseenter="hovering = true"/)
  assert.match(source, /@mouseleave="hovering = false"/)
  assert.match(source, /@focus="handleFocus"/)
  assert.match(source, /@blur="handleBlur"/)
  assert.match(source, /if \(props\.focusable\) focused\.value = true/)
  assert.match(source, /focused:\s*props\.focusable && focused\.value/)
  assert.match(source, /prefers-reduced-motion:\s*reduce/)
})


test('balanced sidebar owns search and keeps primary actions together', () => {
  const sidebar = readFileSync(
    new URL('../src/views/knowledge/components/KnowledgeSidebar.vue', import.meta.url),
    'utf8',
  )
  const workbench = readFileSync(
    new URL('../src/views/knowledge/KnowledgeWorkbench.vue', import.meta.url),
    'utf8',
  )

  assert.ok(sidebar.indexOf('class="search-box"') < sidebar.indexOf('class="sidebar-header"'))
  assert.match(sidebar, /placeholder="搜索已发布知识"/)
  assert.match(sidebar, /@keyup\.enter="\$emit\('search'\)"/)
  assert.match(sidebar, /<button class="search-submit"[^>]*@click="\$emit\('search'\)"/)
  assert.match(sidebar, /@update:model-value="\$emit\('update:search-query', \$event\)"/)
  assert.match(sidebar, /<div class="sidebar-actions">\s*<button v-if="canCreateLibrary"[^>]*\$emit\('create-library'\)[\s\S]*?新建知识库[\s\S]*?<\/button>\s*<button v-if="canReview"[^>]*\$emit\('open-approvals'\)[\s\S]*?审批队列[\s\S]*?<\/button>\s*<\/div>/)
  assert.doesNotMatch(workbench, /class="page-bar"/)
})


test('sidebar rows expose category, overflow, member, delete, and distinct create controls', () => {
  const sidebar = readFileSync(
    new URL('../src/views/knowledge/components/KnowledgeSidebar.vue', import.meta.url),
    'utf8',
  )

  assert.match(sidebar, /import\s*\{\s*LIBRARY_CATEGORIES\s*\}\s*from\s*['"]\.\.\/knowledgeUi\.js['"]/)
  assert.match(sidebar, /LIBRARY_CATEGORIES\[library\.category\]/)
  assert.match(sidebar, /<OverflowTooltip\s+:text="library\.name"\s+:focusable="false"/)
  assert.match(sidebar, /<OverflowTooltip\s+:text="data\.title"\s+:focusable="false"/)
  assert.match(sidebar, /<OverflowTooltip\s+:text="library\.name"\s+:focusable="false"\s*\/?>[\s\S]*?v-if="canManageMembers && library\.role === 'admin'"[\s\S]*?@click\.stop="\$emit\('open-members', library\)"/)
  assert.match(sidebar, /roleLabel\(library\.role\)/)
  assert.match(sidebar, /@click\.stop="\$emit\('delete-library', library\)"/)
  assert.match(sidebar, /@click\.stop="\$emit\('delete-node', data\)"/)
  assert.match(sidebar, /class="create-node create-folder"[\s\S]*?<FolderAdd/)
  assert.match(sidebar, /class="create-node create-document"[\s\S]*?<DocumentAdd/)
  assert.match(sidebar, /\.category-icon\.company[\s\S]*?var\(--color-primary\)[\s\S]*?var\(--color-primary-light\)/)
  assert.match(sidebar, /\.category-icon\.department[\s\S]*?var\(--color-info-text\)[\s\S]*?var\(--color-info-bg\)/)
  assert.match(sidebar, /\.category-icon\.personal[\s\S]*?var\(--color-success-text\)[\s\S]*?var\(--color-success-bg\)/)
  assert.match(sidebar, /\.create-folder\s*\{[^}]*color:\s*var\(--card-bg\)[^}]*background:\s*var\(--color-info-text\)[^}]*\}/)
  assert.match(sidebar, /\.create-document\s*\{[^}]*color:\s*var\(--card-bg\)[^}]*background:\s*var\(--color-primary\)[^}]*\}/)
  assert.doesNotMatch(sidebar, /#[\da-f]{3,8}\b/i)
})


test('sidebar collapse is accessible, persisted, and opens search with focus', () => {
  const sidebar = readFileSync(
    new URL('../src/views/knowledge/components/KnowledgeSidebar.vue', import.meta.url),
    'utf8',
  )
  const workbench = readFileSync(
    new URL('../src/views/knowledge/KnowledgeWorkbench.vue', import.meta.url),
    'utf8',
  )

  assert.match(sidebar, /:aria-expanded="!collapsed"/)
  assert.match(sidebar, /watch\(\(\) => props\.collapsed/)
  assert.match(sidebar, /nextTick\(\(\) => searchInput\.value\?\.focus\(\)\)/)
  assert.match(sidebar, /<div v-else class="collapsed-actions"[\s\S]*?aria-label="搜索已发布知识"[\s\S]*?\$emit\('create-library'\)[\s\S]*?\$emit\('open-approvals'\)[\s\S]*?<\/div>/)
  assert.match(sidebar, /<div v-if="libraries\.length && collapsed" class="collapsed-libraries"[\s\S]*?@click="\$emit\('select-library', library\.id\)"/)
  assert.match(sidebar, /class="collapse-toggle"[\s\S]*?aria-label="collapsed \? '展开知识库侧栏' : '收起知识库侧栏'"[\s\S]*?@click="\$emit\('toggle-collapse'\)"/)
  assert.match(sidebar, /class="library-item"[^>]*:aria-pressed="library\.id === selectedLibraryId"/)
  assert.match(sidebar, /class="compact-action library-compact"[\s\S]*?:aria-pressed="library\.id === selectedLibraryId"/)
  assert.match(workbench, /import\s*\{[^}]*\breadSidebarCollapsed,\s*writeSidebarCollapsed\s*\}\s*from\s*['"]\.\/knowledgeUi\.js['"]/)
  assert.match(workbench, /const sidebarCollapsed = ref\(readSidebarCollapsed\(\)\)/)
  assert.match(workbench, /writeSidebarCollapsed\(sidebarCollapsed\.value\)/)
  assert.match(workbench, /class="workspace"\s+:class="\{ collapsed: sidebarCollapsed \}"/)
  assert.match(workbench, /\.workspace\.collapsed\s*\{\s*grid-template-columns:\s*54px minmax\(0, 1fr\)/)
  assert.doesNotMatch(workbench, /transition:\s*[^;}]*\b(?:width|grid-template-columns)\b/)
})


test('sidebar content owns its scroll space while the collapse footer stays reachable', () => {
  const sidebar = readFileSync(
    new URL('../src/views/knowledge/components/KnowledgeSidebar.vue', import.meta.url),
    'utf8',
  )

  assert.match(sidebar, /class="sidebar-body"/)
  assert.match(sidebar, /\.sidebar-body\s*\{[^}]*flex:\s*1[^}]*min-height:\s*0[^}]*overflow:\s*hidden[^}]*\}/)
  assert.match(sidebar, /\.library-list\s*\{[^}]*min-height:\s*0[^}]*overflow-y:\s*auto[^}]*\}/)
  assert.match(sidebar, /\.tree-section\s*\{[^}]*flex:\s*1[^}]*min-height:\s*0[^}]*overflow:\s*hidden[^}]*\}/)
  assert.match(sidebar, /\.tree-section\s+:deep\(\.el-tree\)\s*\{[^}]*flex:\s*1[^}]*min-height:\s*0[^}]*overflow-y:\s*auto[^}]*\}/)
  assert.match(sidebar, /\.collapse-footer\s*\{[^}]*flex:\s*0 0 auto[^}]*\}/)
})


test('icon controls and motion rules remain accessible and bounded', () => {
  const sidebar = readFileSync(
    new URL('../src/views/knowledge/components/KnowledgeSidebar.vue', import.meta.url),
    'utf8',
  )
  const workbench = readFileSync(
    new URL('../src/views/knowledge/KnowledgeWorkbench.vue', import.meta.url),
    'utf8',
  )

  for (const className of ['search-submit', 'compact-action', 'row-action member-action', 'row-delete', 'create-node create-folder', 'create-node create-document', 'compact-action library-compact', 'collapse-toggle']) {
    const escapedClass = className.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    assert.match(sidebar, new RegExp(`<button[\\s\\S]{0,180}?class="${escapedClass}"[\\s\\S]{0,220}?:aria-label=|<button[\\s\\S]{0,180}?class="${escapedClass}"[\\s\\S]{0,220}?aria-label=`), `${className} needs an aria-label`)
  }
  for (const className of ['search-submit', 'sidebar-action', 'compact-action', 'row-action', 'row-delete', 'create-node', 'collapse-toggle', 'library-item']) {
    assert.match(sidebar, new RegExp(`\\.${className}:focus-visible`), `${className} needs focus-visible styling`)
  }

  assert.match(sidebar, /transition:\s*transform 120ms cubic-bezier\([^)]+\),\s*color 120ms ease,\s*background-color 120ms ease,\s*opacity 120ms ease/)
  const hoverMedia = sidebar.indexOf('@media (hover: hover) and (pointer: fine)')
  const reducedMotion = sidebar.indexOf('@media (prefers-reduced-motion: reduce)')
  const pressRule = sidebar.slice(hoverMedia, reducedMotion)
  assert.match(pressRule, /:active:not\(:focus-visible\)[^{}]*\{\s*transform:\s*scale\(\.97\)/)
  assert.doesNotMatch(pressRule, /:active(?!:not\(:focus-visible\))[^,{]*(?:,|\{)/)
  assert.doesNotMatch(sidebar.slice(0, hoverMedia), /:active[^{}]*\{[^}]*scale\(/)
  assert.doesNotMatch(pressRule, /(?:library-item|library-compact|collapse-toggle):active/)
  assert.doesNotMatch(sidebar, /transition:\s*all\b/)
  assert.doesNotMatch(sidebar, /\bease-in(?:\s|,|;|\))/)
  assert.doesNotMatch(sidebar, /scale\(\s*0(?:\s*[,)]|\.)/)
  assert.doesNotMatch(`${sidebar}\n${workbench}`, /transition:\s*[^;}]*\b(?:width|grid-template-columns)\b/)

  assert.ok(hoverMedia >= 0 && hoverMedia < reducedMotion)
  assert.doesNotMatch(sidebar.slice(0, hoverMedia), /:hover/)
  assert.doesNotMatch(sidebar.slice(reducedMotion), /:hover/)
  assert.match(sidebar.slice(reducedMotion), /:active[^{}]*\{\s*transform:\s*none;/)
})


test('workbench passes review permissions and opens members for the clicked library', () => {
  const workbench = readFileSync(
    new URL('../src/views/knowledge/KnowledgeWorkbench.vue', import.meta.url),
    'utf8',
  )

  assert.match(workbench, /const canReviewApprovals = computed\(\(\) => auth\.hasPermission\('knowledge:review'\) \|\| auth\.hasPermission\('knowledge:admin'\)\)/)
  assert.match(workbench, /:can-manage-members="canCreateLibrary"/)
  assert.match(workbench, /:can-review="canReviewApprovals"/)
  assert.match(workbench, /@open-members="openMembers"/)
  assert.match(workbench, /async function openMembers\(library\)[\s\S]*?`\/libraries\/\$\{library\.id\}\/members`/)
  const saveMembers = workbench.slice(workbench.indexOf('async function saveMembers'), workbench.indexOf('async function openApprovals'))
  assert.match(saveMembers, /`\/libraries\/\$\{memberLibrary\.value\.id\}\/members`/)
  assert.doesNotMatch(saveMembers, /selectedLibraryId\.value/)
})


test('library creation requires an explicit category and resets to company after success', () => {
  const workbench = readFileSync(
    new URL('../src/views/knowledge/KnowledgeWorkbench.vue', import.meta.url),
    'utf8',
  )

  assert.match(workbench, /import\s*\{\s*LIBRARY_CATEGORIES,\s*isDuplicateMember,\s*readSidebarCollapsed,\s*writeSidebarCollapsed\s*\}\s*from\s*['"]\.\/knowledgeUi\.js['"]/) 
  assert.match(workbench, /const libraryForm = reactive\(\{ name: '', description: '', category: 'company' \}\)/)
  assert.match(workbench, /<el-form-item label="知识库分类" required>[\s\S]*?<el-radio-group v-model="libraryForm\.category"[\s\S]*?v-for="\(category, key\) in LIBRARY_CATEGORIES"[\s\S]*?:value="key"[\s\S]*?\{\{ category\.label \}\}[\s\S]*?<\/el-radio-group>/)
  const createLibrary = workbench.slice(workbench.indexOf('async function createLibrary'), workbench.indexOf('function openNodeDialog'))
  assert.match(createLibrary, /knowledgeClient\.post\('\/libraries',\s*\{ \.\.\.libraryForm \}\)/)
  assert.match(createLibrary, /Object\.assign\(libraryForm,\s*\{ name: '', description: '', category: 'company' \}\)/)
})


test('member permissions use Ark usernames, remote candidates, and an explicit add action', () => {
  const workbench = readFileSync(
    new URL('../src/views/knowledge/KnowledgeWorkbench.vue', import.meta.url),
    'utf8',
  )

  assert.match(workbench, /:title="`成员权限 · \$\{memberLibrary\?\.name \|\| ''\}`"/)
  assert.doesNotMatch(workbench, /POC 使用方舟用户 ID|请填写成员用户 ID|<el-input-number/)
  assert.match(workbench, /class="member-identity"[\s\S]*?class="member-username"[\s\S]*?\{\{ member\.username \}\}[\s\S]*?class="member-real-name"[\s\S]*?\{\{ member\.real_name \|\| '未设置姓名' \}\}/)
  assert.match(workbench, /<el-select[\s\S]*?v-model="candidateUserId"[\s\S]*?filterable[\s\S]*?remote[\s\S]*?:remote-method="searchMemberCandidates"[\s\S]*?:loading="memberSearchLoading"[\s\S]*?placeholder="输入方舟用户名或姓名搜索"/)
  assert.match(workbench, /<el-select[\s\S]*?v-model="candidateUserId"[\s\S]*?reserve-keyword[\s\S]*?:remote-method="searchMemberCandidates"/)
  assert.match(workbench, /v-for="candidate in memberCandidates"[\s\S]*?:value="candidate\.user_id"[\s\S]*?candidate\.username[\s\S]*?candidate\.real_name/)
  assert.match(workbench, /<GlassButton[^>]*:disabled="!candidateUserId \|\| memberSaving"[^>]*@click="addSelectedMember"[^>]*>添加成员<\/GlassButton>/)
  assert.doesNotMatch(workbench, /@change="addSelectedMember"/)

  const searchMembers = workbench.slice(workbench.indexOf('async function searchMemberCandidates'), workbench.indexOf('function addSelectedMember'))
  assert.match(searchMembers, /`\/libraries\/\$\{targetLibraryId\}\/member-candidates`/)
  assert.match(searchMembers, /params:\s*\{ q:\s*trimmed,\s*limit:\s*20 \}/)
  assert.match(searchMembers, /memberSearchLoading\.value = true/)
  assert.doesNotMatch(searchMembers, /members\.value\s*=/)
  assert.doesNotMatch(searchMembers, /memberDialog\.value\s*=/)
  assert.match(searchMembers, /catch[\s\S]*?memberCandidates\.value = \[\][\s\S]*?msgError\('成员搜索失败，请重试'\)/)
  assert.match(searchMembers, /msgError\('成员搜索失败，请重试'\)/)

  const addMember = workbench.slice(workbench.indexOf('function addSelectedMember'), workbench.indexOf('async function saveMembers'))
  assert.match(addMember, /isDuplicateMember\(members\.value, candidate\.user_id\)/)
  assert.match(addMember, /msgError\('该成员已在权限列表中'\)/)
  assert.match(addMember, /members\.value\.push\(\{[\s\S]*?user_id:\s*candidate\.user_id,[\s\S]*?username:\s*candidate\.username,[\s\S]*?real_name:\s*candidate\.real_name,[\s\S]*?role:\s*'viewer'/)
})


test('member loading is race-safe, failure-safe, and save uses the loaded library only', () => {
  const workbench = readFileSync(
    new URL('../src/views/knowledge/KnowledgeWorkbench.vue', import.meta.url),
    'utf8',
  )

  assert.match(workbench, /const memberLoadRequest = ref\(0\)/)
  const openMembers = workbench.slice(workbench.indexOf('async function openMembers'), workbench.indexOf('async function searchMemberCandidates'))
  assert.match(openMembers, /const requestId = \+\+memberLoadRequest\.value/)
  assert.match(openMembers, /const loadedMembers = unwrap\(await knowledgeClient\.get\(`\/libraries\/\$\{library\.id\}\/members`,\s*\{ suppressToast: true \}\)\)/)
  assert.doesNotMatch(openMembers.slice(0, openMembers.indexOf('const loadedMembers')), /members\.value\s*=|memberLibrary\.value\s*=|memberDialog\.value\s*=/)
  assert.match(openMembers, /if \(requestId !== memberLoadRequest\.value\) return/)
  assert.ok(openMembers.indexOf('members.value = loadedMembers') < openMembers.indexOf('memberLibrary.value = library'))
  assert.ok(openMembers.indexOf('memberLibrary.value = library') < openMembers.indexOf('memberDialog.value = true'))
  assert.match(openMembers, /catch[\s\S]*?if \(requestId === memberLoadRequest\.value\) msgError\('成员加载失败，请重新点击成员权限'\)/)

  const saveMembers = workbench.slice(workbench.indexOf('async function saveMembers'), workbench.indexOf('function resetMemberDialog'))
  assert.match(saveMembers, /if \(!memberLibrary\.value\) return msgError\('请重新选择知识库'\)/)
  assert.match(saveMembers, /const payload = \{\s*members:\s*members\.value\.map\(member => \(\{ user_id:\s*member\.user_id, role:\s*member\.role \}\)\),?\s*\}/)
  assert.match(saveMembers, /knowledgeClient\.put\(`\/libraries\/\$\{memberLibrary\.value\.id\}\/members`, payload, \{ suppressToast: true \}\)/)
  assert.match(saveMembers, /catch\s*\(error\)/)
  assert.match(saveMembers, /error\.response\?\.data\?\.detail\?\.invalid_user_ids/)
  assert.match(saveMembers, /invalidMemberIds\.value = invalidUserIds/)
  assert.match(saveMembers, /msgError\('部分成员账号已失效，请移除后重试'\)/)
  assert.ok(saveMembers.indexOf('await knowledgeClient.put') < saveMembers.indexOf('memberDialog.value = false'))

  const resetMemberDialog = workbench.slice(workbench.indexOf('function resetMemberDialog'), workbench.indexOf('async function openApprovals'))
  assert.match(workbench, /<el-dialog[^>]*v-model="memberDialog"[^>]*@closed="resetMemberDialog"/)
  assert.match(resetMemberDialog, /memberLibrary\.value = null/)
  assert.match(resetMemberDialog, /memberLoadRequest\.value \+= 1/)
  assert.match(resetMemberDialog, /memberCandidates\.value = \[\]/)
  assert.match(resetMemberDialog, /candidateUserId\.value = null/)
})


test('member requests use local feedback without global loading or duplicate error toasts', () => {
  const workbench = readFileSync(
    new URL('../src/views/knowledge/KnowledgeWorkbench.vue', import.meta.url),
    'utf8',
  )

  const openMembers = workbench.slice(workbench.indexOf('async function openMembers'), workbench.indexOf('async function searchMemberCandidates'))
  assert.match(openMembers, /knowledgeClient\.get\(`\/libraries\/\$\{library\.id\}\/members`,\s*\{ suppressToast: true \}\)/)

  const searchMembers = workbench.slice(workbench.indexOf('async function searchMemberCandidates'), workbench.indexOf('function addSelectedMember'))
  assert.match(searchMembers, /\{\s*params:\s*\{ q:\s*trimmed,\s*limit:\s*20 \},\s*showLoading:\s*false,\s*suppressToast:\s*true,?\s*\}/)
  assert.match(searchMembers, /msgError\('成员搜索失败，请重试'\)/)
})


test('member replacement is single-flight and locks every draft-changing control', () => {
  const workbench = readFileSync(
    new URL('../src/views/knowledge/KnowledgeWorkbench.vue', import.meta.url),
    'utf8',
  )

  assert.match(workbench, /const memberSaving = ref\(false\)/)
  assert.match(workbench, /<el-dialog[\s\S]*?:close-on-click-modal="!memberSaving"[\s\S]*?:close-on-press-escape="!memberSaving"[\s\S]*?:show-close="!memberSaving"/)
  assert.match(workbench, /<el-select[\s\S]*?v-model="candidateUserId"[\s\S]*?:disabled="memberSaving"/)
  assert.match(workbench, /<GlassButton[^>]*:disabled="!candidateUserId \|\| memberSaving"[^>]*@click="addSelectedMember"/)
  assert.match(workbench, /<el-select v-model="member\.role"[^>]*:disabled="memberSaving \|\| isProtectedActor\(member\) \|\| invalidMemberIds\.includes\(member\.user_id\)"/)
  assert.match(workbench, /<GlassButton[^>]*v-else[^>]*:disabled="memberSaving"[^>]*@click="removeMember\(index\)"[^>]*>移除<\/GlassButton>/)
  assert.match(workbench, /<GlassButton[^>]*:disabled="memberSaving"[^>]*@click="memberDialog = false">取消<\/GlassButton>/)
  assert.match(workbench, /<GlassButton[^>]*:loading="memberSaving"[^>]*@click="saveMembers">保存权限<\/GlassButton>/)

  const addMember = workbench.slice(workbench.indexOf('function addSelectedMember'), workbench.indexOf('function removeMember'))
  assert.match(addMember, /if \(memberSaving\.value\) return/)
  const removeMember = workbench.slice(workbench.indexOf('function removeMember'), workbench.indexOf('async function saveMembers'))
  assert.match(removeMember, /if \(memberSaving\.value\) return/)

  const saveMembers = workbench.slice(workbench.indexOf('async function saveMembers'), workbench.indexOf('function resetMemberDialog'))
  assert.match(saveMembers, /if \(memberSaving\.value\) return/)
  assert.match(saveMembers, /memberSaving\.value = true/)
  assert.match(saveMembers, /try\s*\{[\s\S]*?await knowledgeClient\.put[\s\S]*?await loadLibraries\(\)[\s\S]*?memberDialog\.value = false/)
  assert.match(saveMembers, /finally\s*\{\s*memberSaving\.value = false\s*\}/)
  assert.match(saveMembers, /catch\s*\(error\)/)
})


test('invalid members stay visible and are marked for removal after save validation', () => {
  const workbench = readFileSync(
    new URL('../src/views/knowledge/KnowledgeWorkbench.vue', import.meta.url),
    'utf8',
  )

  assert.match(workbench, /const invalidMemberIds = ref\(\[\]\)/)
  assert.match(workbench, /:class="\{ 'member-row-invalid': invalidMemberIds\.includes\(member\.user_id\) \}"/)
  assert.match(workbench, /v-if="invalidMemberIds\.includes\(member\.user_id\)"[^>]*>账号已停用或删除，请移除后重试<\/span>/)
  const removeMember = workbench.slice(workbench.indexOf('function removeMember'), workbench.indexOf('async function saveMembers'))
  assert.match(removeMember, /invalidMemberIds\.value = invalidMemberIds\.value\.filter\(userId => userId !== removed\.user_id\)/)
  const reset = workbench.slice(workbench.indexOf('function resetMemberDialog'), workbench.indexOf('async function openApprovals'))
  assert.match(reset, /invalidMemberIds\.value = \[\]/)
})


test('non-super current administrator is visibly protected using the real auth fields', () => {
  const workbench = readFileSync(
    new URL('../src/views/knowledge/KnowledgeWorkbench.vue', import.meta.url),
    'utf8',
  )

  assert.match(workbench, /const isSuperAdmin = computed\(\(\) => auth\.roles\.includes\('super_admin'\)\)/)
  const guard = workbench.slice(workbench.indexOf('function isProtectedActor'), workbench.indexOf('async function openMembers'))
  assert.match(guard, /!isSuperAdmin\.value/)
  assert.match(guard, /member\.role === 'admin'/)
  assert.match(guard, /Number\(member\.user_id\) === Number\(auth\.user\?\.id\)/)
  assert.match(workbench, /v-if="isProtectedActor\(member\)"[^>]*>当前账号，管理员权限不可移除<\/span>/)
})


test('member dialog has accessible selects and a single-column small-screen layout', () => {
  const workbench = readFileSync(
    new URL('../src/views/knowledge/KnowledgeWorkbench.vue', import.meta.url),
    'utf8',
  )

  assert.match(workbench, /:title="`成员权限 · \$\{memberLibrary\?\.name \|\| ''\}`"[\s\S]*?width="min\(620px, calc\(100vw - 32px\)\)"/)
  assert.match(workbench, /v-model="candidateUserId"[\s\S]*?aria-label="搜索并选择方舟成员"/)
  assert.match(workbench, /<el-select v-model="member\.role"[^>]*:aria-label="`设置 \$\{member\.username\} 的权限`"/)
  const mobileStyles = workbench.slice(workbench.indexOf('@media (max-width: 640px)'))
  assert.match(mobileStyles, /\.member-add\s*\{\s*grid-template-columns:\s*minmax\(0, 1fr\)/)
  assert.match(mobileStyles, /\.member-row\s*\{\s*grid-template-columns:\s*minmax\(0, 1fr\)/)
  assert.doesNotMatch(workbench, /memberCandidateQuery/)
})

