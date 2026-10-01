<template>
  <div class="knowledge-page">
    <el-alert v-if="selectedLibrary?.managed_by === 'announcement'" type="info" :closable="false" title="公告库由公告管理维护">
      <router-link to="/announcements">前往公告管理进行新建、编辑与审核</router-link>
    </el-alert>
    <ListPageStatus :paged="false" :error="librariesResource.errorMessage.value" :loading="librariesResource.loading.value" :has-data="librariesResource.hasData.value" @retry="loadLibraries" />
    <ListPageStatus :paged="false" :error="treeResource.errorMessage.value" :loading="treeResource.loading.value" :has-data="treeResource.hasData.value" @retry="loadTree" />
    <ListPageStatus :paged="false" :error="documentResource.errorMessage.value" :loading="documentResource.loading.value" :has-data="documentResource.hasData.value" @retry="documentResource.load()" />
    <div class="workspace" :class="{ collapsed: sidebarCollapsed }">
      <KnowledgeSidebar
        :libraries="libraries"
        :libraries-loading="librariesResource.loading.value"
        :libraries-error="librariesResource.errorMessage.value"
        :selected-library-id="selectedLibraryId"
        :tree="nestedTree"
        :tree-loaded="treeResource.hasLoaded.value"
        :search-query="searchQuery"
        :applied-search-query="appliedSearchQuery"
        :collapsed="sidebarCollapsed"
        :can-write="canWriteLibrary"
        :can-create-library="canCreateLibrary"
        :can-review="canReviewApprovals"
        :can-manage-members="canCreateLibrary && !selectedLibrary?.managed_by"
        :can-delete-library="canCreateLibrary && !selectedLibrary?.managed_by"
        :can-delete-node="canWriteLibrary && capabilities.deleteNode"
        @update:search-query="searchQuery = $event"
        @search="runSearch"
        @reset-search="resetSearch"
        @toggle-collapse="toggleSidebar"
        @select-library="selectLibrary"
        @select-document="selectDocument"
        @create-library="libraryDialog = true"
        @create-node="openNodeDialog"
        @open-approvals="openApprovals"
        @open-members="openMembers"
        @delete-library="deleteLibrary"
        @delete-node="deleteNode"
      />
      <KnowledgeEditor
        :document="document"
        :role="selectedLibrary?.managed_by ? 'viewer' : (selectedLibrary?.role || 'viewer')"
        :saving="saving"
        @save="saveDocument"
        @submit="submitDocument"
        @delete="deleteNode"
        @ai-applied="handleAiApplied"
        @dirty-change="dirty = $event"
      />
    </div>

    <el-dialog v-model="libraryDialog" title="新建知识库" width="480px">
      <el-form label-position="top">
        <el-form-item label="知识库名称" required><el-input v-model="libraryForm.name" maxlength="128" /></el-form-item>
        <el-form-item label="知识库分类" required>
          <el-radio-group v-model="libraryForm.category" class="category-options">
            <el-radio-button v-for="(category, key) in LIBRARY_CATEGORIES" :key="key" :value="key">
              {{ category.label }}
            </el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="用途说明"><el-input v-model="libraryForm.description" type="textarea" :rows="3" maxlength="512" /></el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="libraryDialog = false">取消</GlassButton>
        <GlassButton variant="primary" @click="createLibrary">创建知识库</GlassButton>
      </template>
    </el-dialog>

    <el-dialog v-model="nodeDialog" :title="nodeForm.node_type === 'folder' ? '新建目录' : '新建文档'" width="480px">
      <el-form label-position="top">
        <el-form-item label="名称" required><el-input v-model="nodeForm.title" maxlength="256" @keyup.enter="createNode" /></el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="nodeDialog = false">取消</GlassButton>
        <GlassButton variant="primary" @click="createNode">创建</GlassButton>
      </template>
    </el-dialog>

    <KnowledgeMemberDialog
      v-model="memberDialog"
      v-model:candidate-user-id="candidateUserId"
      :library="memberLibrary"
      :members="members"
      :candidates="memberCandidates"
      :invalid-user-ids="invalidMemberIds"
      :protected-user-id="protectedActorUserId"
      :search-loading="memberSearchLoading"
      :read-loading="membersResource.loading.value"
      :read-error="membersResource.errorMessage.value"
      :read-loaded="membersResource.hasLoaded.value"
      :search-error="candidatesResource.errorMessage.value"
      @retry="retryMembers"
      @retry-search="candidatesResource.load()"
      :saving="memberSaving"
      @closed="resetMemberDialog"
      @search="searchMemberCandidates"
      @add="addSelectedMember"
      @remove="removeMember"
      @save="saveMembers"
    />

    <el-dialog v-model="searchDialog" title="搜索结果" width="760px">
      <ListPageStatus :paged="false" :error="searchResource.errorMessage.value" :loading="searching" :has-data="searchResource.hasData.value" @retry="searchResource.load()" />
      <el-empty v-if="searchResource.isEmpty.value" description="没有找到已发布内容" />
      <button v-for="item in searchResults" :key="item.document_id" class="search-result" type="button" @click="openSearchResult(item)">
        <strong>{{ item.title }}</strong><span>{{ item.summary }}</span>
      </button>
    </el-dialog>

    <KnowledgeApprovalDialog
      v-model="reviewDialog"
      :detail="reviewDetail"
      :read-error="reviewResource.errorMessage.value"
      :read-loading="reviewResource.loading.value"
      @retry="reviewResource.load()"
      @approve="approve(reviewDetail, $event)"
      @reject="reject(reviewDetail)"
    />

    <ApprovalQueue v-model="approvalDrawer" :items="approvals" :read-error="approvalsResource.errorMessage.value" :read-loading="approvalsResource.loading.value" :read-loaded="approvalsResource.hasLoaded.value" @retry="approvalsResource.load()" @inspect="inspectApproval" />
  </div>
</template>

<script setup>import { confirmAction, promptAction, msgError, msgSuccess } from '@/utils/feedback'
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'

import { useAsyncResource } from '@/composables/useAsyncResource'
import { knowledgeClient } from '@/api/clients'
import { useAuthStore } from '@/stores/auth'
import { capabilitiesFor } from './knowledgeState.js'
import { LIBRARY_CATEGORIES, isDuplicateMember, readSidebarCollapsed, writeSidebarCollapsed } from './knowledgeUi.js'
import KnowledgeSidebar from './components/KnowledgeSidebar.vue'
import KnowledgeEditor from './components/KnowledgeEditor.vue'
import KnowledgeApprovalDialog from './components/KnowledgeApprovalDialog.vue'
import KnowledgeMemberDialog from './components/KnowledgeMemberDialog.vue'
import ApprovalQueue from './components/ApprovalQueue.vue'

const auth = useAuthStore()
const readOptions = signal => ({ signal, showLoading: false, suppressToast: true })
const librariesResource = useAsyncResource(async (_, { signal }) => unwrap(await knowledgeClient.get('/libraries', readOptions(signal))), { initialData: [] })
const treeResource = useAsyncResource(async (id, { signal }) => id ? unwrap(await knowledgeClient.get(`/libraries/${id}/tree`, readOptions(signal))) : [], { initialData: [] })
const documentResource = useAsyncResource(async ({ id }, { signal }) => unwrap(await knowledgeClient.get(`/documents/${id}`, readOptions(signal))))
const approvalsResource = useAsyncResource(async (_, { signal }) => unwrap(await knowledgeClient.get('/approvals', readOptions(signal))), { initialData: [] })
const reviewResource = useAsyncResource(async (id, { signal }) => unwrap(await knowledgeClient.get(`/approvals/${id}`, readOptions(signal))))
const membersResource = useAsyncResource(async (id, { signal }) => unwrap(await knowledgeClient.get(`/libraries/${id}/members`, readOptions(signal))), { initialData: [] })
const candidatesResource = useAsyncResource(async ({ libraryId, query }, { signal }) => unwrap(await knowledgeClient.get(`/libraries/${libraryId}/member-candidates`, { ...readOptions(signal), params: { q: query, limit: 20 } })), { initialData: [] })
const searchResource = useAsyncResource(async (query, { signal }) => unwrap(await knowledgeClient.get('/search', { ...readOptions(signal), params: { q: query, limit: 20 } })), { initialData: [] })
const libraries = librariesResource.data, tree = treeResource.data, document = documentResource.data
const selectedLibraryId = ref(null)
const dirty = ref(false)
const saving = ref(false)
const libraryDialog = ref(false)
const nodeDialog = ref(false)
const memberDialog = ref(false)
const approvalDrawer = ref(false)
const searchDialog = ref(false)
const reviewDialog = ref(false)
const reviewDetail = reviewResource.data
const approvals = approvalsResource.data
const members = membersResource.data
const memberLibrary = ref(null)
const memberCandidates = candidatesResource.data
let candidateScope = null
const candidateUserId = ref(null)
const memberSearchLoading = candidatesResource.loading
const memberSaving = ref(false)
const invalidMemberIds = ref([])
const searchQuery = ref('')
const searchResults = searchResource.data
const searching = searchResource.loading
const appliedSearchQuery = ref('')
const sidebarCollapsed = ref(readSidebarCollapsed())
const libraryForm = reactive({ name: '', description: '', category: 'company' })
const nodeForm = reactive({ title: '', node_type: 'document' })
const selectedLibrary = computed(() => libraries.value.find(item => item.id === selectedLibraryId.value))
const capabilities = computed(() => capabilitiesFor(selectedLibrary.value?.role))
const canWriteLibrary = computed(() => !selectedLibrary.value?.managed_by && capabilities.value.write && auth.hasAnyPermission(['knowledge:write', 'knowledge:admin']))
const canCreateLibrary = computed(() => auth.hasPermission('knowledge:admin'))
const canReviewApprovals = computed(() => auth.hasPermission('knowledge:review') || auth.hasPermission('knowledge:admin'))
const isSuperAdmin = computed(() => auth.roles.includes('super_admin'))
const protectedActorUserId = computed(() => isSuperAdmin.value ? null : Number(auth.user?.id))
const nestedTree = computed(() => {
  const map = new Map(tree.value.map(item => [item.id, { ...item, children: [] }]))
  const roots = []
  for (const node of map.values()) {
    const parent = map.get(node.parent_id)
    if (parent) parent.children.push(node)
    else roots.push(node)
  }
  return roots
})
function unwrap(response) { return response.data }
function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  writeSidebarCollapsed(sidebarCollapsed.value)
}
async function loadLibraries() {
  const success = await librariesResource.load()
  if (!success) return false
  if (!libraries.value.some(item => item.id === selectedLibraryId.value)) {
    treeResource.clear(); documentResource.clear(); dirty.value = false
    selectedLibraryId.value = libraries.value[0]?.id || null
  }
  if (selectedLibraryId.value) await loadTree()
  return true
}
function loadTree() { return treeResource.load(selectedLibraryId.value) }
async function selectLibrary(id) {
  if (selectedLibraryId.value === id) return true
  if (!(await allowDiscard())) return false
  treeResource.clear(); documentResource.clear(); searchResource.clear()
  selectedLibraryId.value = id
  searchQuery.value = ''
  appliedSearchQuery.value = ''
  await loadTree()
  return true
}

function reloadDocument(id) { return documentResource.load({ id, libraryId: selectedLibraryId.value }) }

async function selectDocument(id) {
  if (document.value?.id === id) return
  if (!(await allowDiscard())) return
  documentResource.clear()
  await reloadDocument(id)
}

async function createLibrary() {
  if (!libraryForm.name.trim()) return msgError('请填写知识库名称')
  const created = unwrap(await knowledgeClient.post('/libraries', { ...libraryForm }))
  libraryDialog.value = false
  Object.assign(libraryForm, { name: '', description: '', category: 'company' })
  await loadLibraries()
  await selectLibrary(created.id)
  msgSuccess('创建')
}

function openNodeDialog(type) {
  Object.assign(nodeForm, { title: '', node_type: type })
  nodeDialog.value = true
}

async function createNode() {
  if (!nodeForm.title.trim()) return msgError('请填写名称')
  const emptyDoc = { type: 'doc', content: [{ type: 'paragraph' }] }
  const payload = { ...nodeForm, content: nodeForm.node_type === 'document' ? emptyDoc : undefined }
  const created = unwrap(await knowledgeClient.post(`/libraries/${selectedLibraryId.value}/documents`, payload))
  nodeDialog.value = false
  await loadTree()
  if (created.node_type === 'document') await selectDocument(created.id)
  msgSuccess('创建')
}

function nodeContains(rootId, targetId) {
  let current = tree.value.find(item => item.id === targetId)
  while (current) {
    if (current.id === rootId) return true
    current = tree.value.find(item => item.id === current.parent_id)
  }
  return false
}

function deletedCountLabel(result) {
  const total = result.folder_count + result.document_count
  return total > 1 ? `已删除 ${total} 个目录或文档` : '已删除'
}

async function deleteLibrary(library) {
  try {
    await confirmAction(
      `删除知识库“${library.name}”后，其中全部目录、文档和待审批内容都将移除。`,
      '删除知识库',
      { confirmButtonText: '删除知识库', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }
  const result = unwrap(await knowledgeClient.delete(`/libraries/${library.id}`))
  if (selectedLibraryId.value === library.id) {
    dirty.value = false
    document.value = null
    selectedLibraryId.value = null
  }
  await loadLibraries()
  msgSuccess(deletedCountLabel(result))
}

async function deleteNode(node) {
  const typeLabel = node.node_type === 'folder' ? '目录' : '文档'
  const cascade = node.node_type === 'folder' ? '，其全部子目录、文档和待审批内容也将移除' : ''
  try {
    await confirmAction(
      `删除${typeLabel}“${node.title}”${cascade}。`,
      `删除${typeLabel}`,
      { confirmButtonText: `删除${typeLabel}`, cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }
  const removesOpenDocument = Boolean(document.value && nodeContains(node.id, document.value.id))
  const result = unwrap(await knowledgeClient.delete(`/documents/${node.id}`))
  if (removesOpenDocument) {
    dirty.value = false
    document.value = null
  }
  await loadTree()
  msgSuccess(deletedCountLabel(result))
}

async function saveDocument(payload) {
  const targetId = document.value.id
  saving.value = true
  try {
    const result = unwrap(await knowledgeClient.put(`/documents/${targetId}`, { title: payload.title, content: payload.content }))
    await loadTree()
    await nextTick()
    if (document.value?.id === targetId) {
      document.value.title = payload.title
      document.value.content_json = payload.content
      document.value.version_no = result.version_no
      document.value.revision_id = result.id
    }
    payload.done()
    msgSuccess('保存')
  } catch (error) {
    payload.fail?.()
    throw error
  } finally { saving.value = false }
}

async function submitDocument() {
  const targetId = document.value.id
  await knowledgeClient.post(`/documents/${targetId}/submit`)
  await loadTree()
  if (document.value?.id === targetId && !dirty.value) await reloadDocument(targetId)
  msgSuccess('提交审批')
}

async function handleAiApplied() {
  if (!document.value?.id) return
  dirty.value = false
  await Promise.all([loadTree(), reloadDocument(document.value.id)])
}

async function openMembers(library) {
  membersResource.clear(); candidatesResource.clear(); candidateScope = null
  memberLibrary.value = library
  invalidMemberIds.value = []; candidateUserId.value = null
  memberDialog.value = true
  return membersResource.load(library.id)
}
function retryMembers() { return memberLibrary.value ? membersResource.load(memberLibrary.value.id) : false }
function searchMemberCandidates(query) {
  const trimmed = query.trim(), libraryId = memberLibrary.value?.id
  if (!trimmed || !libraryId) { candidatesResource.clear(); candidateScope = null; return false }
  const nextScope = JSON.stringify([libraryId, trimmed])
  const clear = candidateScope !== nextScope
  candidateScope = nextScope
  return candidatesResource.load({ libraryId, query: trimmed }, { clear })
}

function addSelectedMember() {
  if (memberSaving.value) return
  if (membersResource.loading.value || membersResource.error.value || !membersResource.hasLoaded.value) return
  const candidate = memberCandidates.value.find(item => item.user_id === candidateUserId.value)
  if (!candidate) return
  if (isDuplicateMember(members.value, candidate.user_id)) {
    return msgError('该成员已在权限列表中')
  }
  members.value.push({
    user_id: candidate.user_id,
    username: candidate.username,
    real_name: candidate.real_name,
    role: 'viewer',
  })
  candidateUserId.value = null
}

function removeMember(index) {
  if (memberSaving.value) return
  if (membersResource.loading.value || membersResource.error.value) return
  const [removed] = members.value.splice(index, 1)
  invalidMemberIds.value = invalidMemberIds.value.filter(userId => userId !== removed.user_id)
}

async function saveMembers() {
  if (memberSaving.value) return
  if (membersResource.loading.value || membersResource.error.value || !membersResource.hasLoaded.value) return
  if (!memberLibrary.value) return msgError('请重新选择知识库')
  const payload = {
    members: members.value.map(member => ({ user_id: member.user_id, role: member.role })),
  }
  invalidMemberIds.value = []
  memberSaving.value = true
  try {
    await knowledgeClient.put(`/libraries/${memberLibrary.value.id}/members`, payload, { suppressToast: true })
    await loadLibraries()
    memberDialog.value = false
    msgSuccess('保存权限')
  } catch (error) {
    const invalidUserIds = error.response?.data?.detail?.invalid_user_ids
    if (Array.isArray(invalidUserIds) && invalidUserIds.length) {
      invalidMemberIds.value = invalidUserIds
      msgError('部分成员账号已失效，请移除后重试', error)
    } else {
      msgError('成员权限保存失败，请重试', error)
    }
  } finally {
    memberSaving.value = false
  }
}

function resetMemberDialog() {
  membersResource.clear(); candidatesResource.clear(); candidateScope = null
  memberLibrary.value = null
  members.value = []
  memberCandidates.value = []
  candidateUserId.value = null
  invalidMemberIds.value = []
}

function openApprovals() { approvalDrawer.value = true; return approvalsResource.load() }
function inspectApproval(item) {
  reviewResource.clear()
  approvalDrawer.value = false
  reviewDialog.value = true
  return reviewResource.load(item.id)
}

async function approve(item, crossLibraryConfirmed) {
  await knowledgeClient.post(`/approvals/${item.id}/approve`, {
    remark: '批准发布',
    confirm_cross_library_sources: crossLibraryConfirmed,
  })
  approvals.value = approvals.value.filter(row => row.id !== item.id)
  reviewDialog.value = false
  await loadTree()
  if (document.value?.id === item.document_id && !dirty.value) await reloadDocument(item.document_id)
  msgSuccess('发布')
}

async function reject(item) {
  const { value } = await promptAction('请说明需要补充或修改的内容', '驳回审批', { inputType: 'textarea', inputValidator: value => Boolean(value?.trim()) || '驳回原因不能为空' })
  await knowledgeClient.post(`/approvals/${item.id}/reject`, { remark: value })
  approvals.value = approvals.value.filter(row => row.id !== item.id)
  reviewDialog.value = false
  await loadTree()
  msgSuccess('驳回')
}

function runSearch() {
  const query = searchQuery.value.trim()
  if (!query) return msgError('请输入搜索关键词')
  appliedSearchQuery.value = query
  searchDialog.value = true
  return searchResource.load(query)
}
function resetSearch() { searchQuery.value = ''; appliedSearchQuery.value = ''; searchResource.clear(); searchDialog.value = false }
watch(memberDialog, open => { if (!open) resetMemberDialog() })
watch(approvalDrawer, open => { if (!open) approvalsResource.clear() })
watch(reviewDialog, open => { if (!open) reviewResource.clear() })
watch(searchDialog, open => { if (!open) searchResource.clear() })
watch(() => JSON.stringify([auth.user?.id, auth.roles, auth.user?.permissions]), () => {
  for (const resource of [librariesResource, treeResource, documentResource, approvalsResource, reviewResource, membersResource, candidatesResource, searchResource]) resource.clear()
  selectedLibraryId.value = null; dirty.value = false
  memberDialog.value = false; approvalDrawer.value = false; reviewDialog.value = false; searchDialog.value = false
  void loadLibraries()
})
async function openSearchResult(item) {
  const library = libraries.value.find(row => row.id === item.library_id)
  if (library && !(await selectLibrary(library.id))) return
  await selectDocument(item.document_id)
  searchDialog.value = false
}
async function allowDiscard() {
  if (!dirty.value) return true
  try {
    await confirmAction('当前修改尚未保存，离开后将丢失。', '未保存的修改', { confirmButtonText: '放弃修改', cancelButtonText: '继续编辑', type: 'warning' })
    dirty.value = false
    return true
  } catch { return false }
}

function beforeUnload(event) {
  if (!dirty.value) return
  event.preventDefault()
  event.returnValue = ''
}
onBeforeRouteLeave(() => allowDiscard())
onMounted(() => { window.addEventListener('beforeunload', beforeUnload); loadLibraries() })
onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
</script>
<style scoped>
.knowledge-page { display: flex; height: calc(100vh - var(--topbar-height, 64px)); min-height: 620px; flex-direction: column; background: var(--page-bg); }
.workspace { display: grid; min-height: 0; flex: 1; grid-template-columns: 310px minmax(0, 1fr); margin: 14px; overflow: hidden; border: 1px solid var(--border-color); border-radius: var(--radius-xl, 16px); background: var(--surface-card, #fff); box-shadow: var(--shadow-card, 0 8px 30px rgba(30, 36, 50, .06)); }
.workspace.collapsed { grid-template-columns: 54px minmax(0, 1fr); }
.category-options { width: 100%; }
.category-options :deep(.el-radio-button) { flex: 1; }
.category-options :deep(.el-radio-button__inner) { width: 100%; }
.search-result { display: grid; width: 100%; gap: 6px; padding: 14px 4px; border: 0; border-bottom: 1px solid var(--border-color); color: var(--text-primary); background: transparent; cursor: pointer; text-align: left; }
.search-result span { color: var(--text-secondary); font-size: 13px; line-height: 1.6; }
.search-result:focus-visible { outline: 2px solid var(--color-primary); outline-offset: -2px; }
@media (hover: hover) and (pointer: fine) { .search-result:hover { background: var(--color-primary-light); } }
@media (max-width: 900px) { .knowledge-page { height: auto; min-height: calc(100vh - 64px); } .workspace { min-height: 760px; grid-template-columns: minmax(250px, 42vw) minmax(0, 1fr); margin: 8px; } .workspace.collapsed { grid-template-columns: 54px minmax(0, 1fr); } }
@media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto !important; } }
</style>
