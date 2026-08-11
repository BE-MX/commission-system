<template>
  <div class="knowledge-page">
    <div class="workspace" :class="{ collapsed: sidebarCollapsed }">
      <KnowledgeSidebar
        :libraries="libraries"
        :selected-library-id="selectedLibraryId"
        :tree="nestedTree"
        :search-query="searchQuery"
        :collapsed="sidebarCollapsed"
        :can-write="capabilities.write"
        :can-create-library="canCreateLibrary"
        :can-review="canReviewApprovals"
        :can-manage-members="canCreateLibrary"
        :can-delete-library="canCreateLibrary"
        :can-delete-node="capabilities.deleteNode"
        @update:search-query="searchQuery = $event"
        @search="runSearch"
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
        :role="selectedLibrary?.role || 'viewer'"
        :saving="saving"
        @save="saveDocument"
        @submit="submitDocument"
        @delete="deleteNode"
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

    <el-dialog v-model="nodeDialog" :title="nodeForm.node_type === 'folder' ? '新建目录' : '新建文档'" width="440px">
      <el-form label-position="top">
        <el-form-item label="名称" required><el-input v-model="nodeForm.title" maxlength="256" @keyup.enter="createNode" /></el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="nodeDialog = false">取消</GlassButton>
        <GlassButton variant="primary" @click="createNode">创建</GlassButton>
      </template>
    </el-dialog>

    <el-dialog
      v-model="memberDialog"
      :title="`成员权限 · ${memberLibrary?.name || ''}`"
      width="min(620px, calc(100vw - 32px))"
      :close-on-click-modal="!memberSaving"
      :close-on-press-escape="!memberSaving"
      :show-close="!memberSaving"
      @closed="resetMemberDialog"
    >
      <div class="member-add">
        <el-select
          :key="memberLibrary?.id || 'closed'"
          v-model="candidateUserId"
          aria-label="搜索并选择方舟成员"
          filterable
          remote
          clearable
          reserve-keyword
          :remote-method="searchMemberCandidates"
          :loading="memberSearchLoading"
          :disabled="memberSaving"
          placeholder="输入方舟用户名或姓名搜索"
        >
          <el-option
            v-for="candidate in memberCandidates"
            :key="candidate.user_id"
            :value="candidate.user_id"
            :label="candidate.real_name ? `${candidate.username} · ${candidate.real_name}` : candidate.username"
          >
            <span class="candidate-username">{{ candidate.username }}</span>
            <span v-if="candidate.real_name" class="candidate-real-name">{{ candidate.real_name }}</span>
          </el-option>
        </el-select>
        <GlassButton variant="ghost" :disabled="!candidateUserId || memberSaving" @click="addSelectedMember">添加成员</GlassButton>
      </div>
      <div class="member-table">
        <el-empty v-if="!members.length" description="暂无已配置成员" :image-size="72" />
        <div
          v-for="(member, index) in members"
          :key="member.user_id"
          class="member-row"
          :class="{ 'member-row-invalid': invalidMemberIds.includes(member.user_id) }"
        >
          <div class="member-identity">
            <span class="member-username">{{ member.username }}</span>
            <span class="member-real-name">{{ member.real_name || '未设置姓名' }}</span>
            <span v-if="invalidMemberIds.includes(member.user_id)" class="member-invalid">账号已停用或删除，请移除后重试</span>
          </div>
          <el-select v-model="member.role" :aria-label="`设置 ${member.username} 的权限`" :disabled="memberSaving || isProtectedActor(member) || invalidMemberIds.includes(member.user_id)">
            <el-option label="只读" value="viewer" /><el-option label="编辑" value="editor" />
            <el-option label="审核" value="reviewer" /><el-option label="管理" value="admin" />
          </el-select>
          <span v-if="isProtectedActor(member)" class="actor-lock">当前账号，管理员权限不可移除</span>
          <GlassButton v-else variant="link" link-tone="danger" :disabled="memberSaving" @click="removeMember(index)">移除</GlassButton>
        </div>
      </div>
      <template #footer>
        <GlassButton variant="ghost" :disabled="memberSaving" @click="memberDialog = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="memberSaving" @click="saveMembers">保存权限</GlassButton>
      </template>
    </el-dialog>

    <el-dialog v-model="searchDialog" title="搜索结果" width="680px">
      <el-empty v-if="!searchResults.length" description="没有找到已发布内容" />
      <button v-for="item in searchResults" :key="item.document_id" class="search-result" type="button" @click="openSearchResult(item)">
        <strong>{{ item.title }}</strong><span>{{ item.summary }}</span>
      </button>
    </el-dialog>

    <el-dialog v-model="reviewDialog" :title="reviewDetail?.title || '审批文档'" width="760px">
      <div v-if="reviewDetail" class="review-detail">
        <div class="review-meta">冻结修订 v{{ reviewDetail.version_no }} · 提交人 ID {{ reviewDetail.submitted_by }}</div>
        <pre>{{ reviewDetail.content_text }}</pre>
      </div>
      <template #footer>
        <GlassButton variant="ghost" @click="reject(reviewDetail)">驳回</GlassButton>
        <GlassButton variant="primary" @click="approve(reviewDetail)">批准并发布此版本</GlassButton>
      </template>
    </el-dialog>

    <ApprovalQueue v-model="approvalDrawer" :items="approvals" @inspect="inspectApproval" />
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { knowledgeClient } from '@/api/clients'
import { useAuthStore } from '@/stores/auth'
import { msgError, msgSuccess } from '@/utils/feedback'
import { capabilitiesFor } from './knowledgeState.js'
import { LIBRARY_CATEGORIES, isDuplicateMember, readSidebarCollapsed, writeSidebarCollapsed } from './knowledgeUi.js'
import KnowledgeSidebar from './components/KnowledgeSidebar.vue'
import KnowledgeEditor from './components/KnowledgeEditor.vue'
import ApprovalQueue from './components/ApprovalQueue.vue'

const auth = useAuthStore()
const libraries = ref([])
const tree = ref([])
const document = ref(null)
const selectedLibraryId = ref(null)
const dirty = ref(false)
const saving = ref(false)
const libraryDialog = ref(false)
const nodeDialog = ref(false)
const memberDialog = ref(false)
const approvalDrawer = ref(false)
const searchDialog = ref(false)
const reviewDialog = ref(false)
const reviewDetail = ref(null)
const approvals = ref([])
const members = ref([])
const memberLibrary = ref(null)
const memberCandidates = ref([])
const candidateUserId = ref(null)
const memberSearchLoading = ref(false)
const memberSaving = ref(false)
const invalidMemberIds = ref([])
const memberLoadRequest = ref(0)
const memberSearchRequest = ref(0)
const searchQuery = ref('')
const searchResults = ref([])
const searching = ref(false)
const sidebarCollapsed = ref(readSidebarCollapsed())
const libraryForm = reactive({ name: '', description: '', category: 'company' })
const nodeForm = reactive({ title: '', node_type: 'document' })

const selectedLibrary = computed(() => libraries.value.find(item => item.id === selectedLibraryId.value))
const capabilities = computed(() => capabilitiesFor(selectedLibrary.value?.role))
const canCreateLibrary = computed(() => auth.hasPermission('knowledge:admin'))
const canReviewApprovals = computed(() => auth.hasPermission('knowledge:review') || auth.hasPermission('knowledge:admin'))
const isSuperAdmin = computed(() => auth.roles.includes('super_admin'))
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
  libraries.value = unwrap(await knowledgeClient.get('/libraries'))
  if (!libraries.value.some(item => item.id === selectedLibraryId.value)) {
    selectedLibraryId.value = libraries.value[0]?.id || null
  }
  if (selectedLibraryId.value) await loadTree()
}

async function loadTree() {
  tree.value = unwrap(await knowledgeClient.get(`/libraries/${selectedLibraryId.value}/tree`))
}

async function selectLibrary(id) {
  if (selectedLibraryId.value === id) return true
  if (!(await allowDiscard())) return false
  selectedLibraryId.value = id
  document.value = null
  await loadTree()
  return true
}

async function reloadDocument(id) {
  document.value = unwrap(await knowledgeClient.get(`/documents/${id}`))
}

async function selectDocument(id) {
  if (document.value?.id === id) return
  if (!(await allowDiscard())) return
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
    await ElMessageBox.confirm(
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
    await ElMessageBox.confirm(
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
    payload.done()
    if (document.value?.id === targetId) document.value.version_no = result.version_no
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

function isProtectedActor(member) {
  return !isSuperAdmin.value
    && member.role === 'admin'
    && Number(member.user_id) === Number(auth.user?.id)
}

async function openMembers(library) {
  const requestId = ++memberLoadRequest.value
  try {
    const loadedMembers = unwrap(await knowledgeClient.get(`/libraries/${library.id}/members`, { suppressToast: true }))
    if (requestId !== memberLoadRequest.value) return
    members.value = loadedMembers
    invalidMemberIds.value = []
    memberLibrary.value = library
    memberCandidates.value = []
    candidateUserId.value = null
    memberDialog.value = true
  } catch {
    if (requestId === memberLoadRequest.value) msgError('成员加载失败，请重新点击成员权限')
  }
}

async function searchMemberCandidates(query) {
  const trimmed = query.trim()
  const targetLibraryId = memberLibrary.value?.id
  const requestId = ++memberSearchRequest.value
  if (!trimmed || !targetLibraryId) {
    memberCandidates.value = []
    memberSearchLoading.value = false
    return
  }
  memberSearchLoading.value = true
  try {
    const results = unwrap(await knowledgeClient.get(
      `/libraries/${targetLibraryId}/member-candidates`,
      { params: { q: trimmed, limit: 20 }, showLoading: false, suppressToast: true },
    ))
    if (requestId !== memberSearchRequest.value || memberLibrary.value?.id !== targetLibraryId) return
    memberCandidates.value = results
  } catch {
    if (requestId === memberSearchRequest.value && memberLibrary.value?.id === targetLibraryId) {
      memberCandidates.value = []
      msgError('成员搜索失败，请重试')
    }
  } finally {
    if (requestId === memberSearchRequest.value) memberSearchLoading.value = false
  }
}

function addSelectedMember() {
  if (memberSaving.value) return
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
  const [removed] = members.value.splice(index, 1)
  invalidMemberIds.value = invalidMemberIds.value.filter(userId => userId !== removed.user_id)
}

async function saveMembers() {
  if (memberSaving.value) return
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
      msgError('部分成员账号已失效，请移除后重试')
    } else {
      msgError('成员权限保存失败，请重试')
    }
  } finally {
    memberSaving.value = false
  }
}

function resetMemberDialog() {
  memberLoadRequest.value += 1
  memberSearchRequest.value += 1
  memberLibrary.value = null
  members.value = []
  memberCandidates.value = []
  candidateUserId.value = null
  memberSearchLoading.value = false
  invalidMemberIds.value = []
}

async function openApprovals() {
  approvals.value = unwrap(await knowledgeClient.get('/approvals'))
  approvalDrawer.value = true
}

async function inspectApproval(item) {
  reviewDetail.value = unwrap(await knowledgeClient.get(`/approvals/${item.id}`))
  approvalDrawer.value = false
  reviewDialog.value = true
}

async function approve(item) {
  await knowledgeClient.post(`/approvals/${item.id}/approve`, { remark: '批准发布' })
  approvals.value = approvals.value.filter(row => row.id !== item.id)
  reviewDialog.value = false
  await loadTree()
  if (document.value?.id === item.document_id && !dirty.value) await reloadDocument(item.document_id)
  msgSuccess('发布')
}

async function reject(item) {
  const { value } = await ElMessageBox.prompt('请说明需要补充或修改的内容', '驳回审批', { inputType: 'textarea', inputValidator: value => Boolean(value?.trim()) || '驳回原因不能为空' })
  await knowledgeClient.post(`/approvals/${item.id}/reject`, { remark: value })
  approvals.value = approvals.value.filter(row => row.id !== item.id)
  reviewDialog.value = false
  await loadTree()
  msgSuccess('驳回')
}

async function runSearch() {
  if (searching.value) return
  const query = searchQuery.value.trim()
  if (!query) return msgError('请输入搜索关键词')
  searching.value = true
  try {
    searchResults.value = unwrap(await knowledgeClient.get('/search', { params: { q: query, limit: 20 } }))
    searchDialog.value = true
  } finally {
    searching.value = false
  }
}

async function openSearchResult(item) {
  const library = libraries.value.find(row => row.id === item.library_id)
  if (library && !(await selectLibrary(library.id))) return
  await selectDocument(item.document_id)
  searchDialog.value = false
}

async function allowDiscard() {
  if (!dirty.value) return true
  try {
    await ElMessageBox.confirm('当前修改尚未保存，离开后将丢失。', '未保存的修改', { confirmButtonText: '放弃修改', cancelButtonText: '继续编辑', type: 'warning' })
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
.knowledge-page { display: flex; height: calc(100vh - var(--topbar-height, 64px)); min-height: 620px; flex-direction: column; background: var(--page-bg, #f5f6fa); }
.workspace { display: grid; min-height: 0; flex: 1; grid-template-columns: 310px minmax(0, 1fr); margin: 14px; overflow: hidden; border: 1px solid var(--border-color); border-radius: var(--radius-xl, 16px); background: var(--surface-card, #fff); box-shadow: var(--shadow-card, 0 8px 30px rgba(30, 36, 50, .06)); }
.workspace.collapsed { grid-template-columns: 54px minmax(0, 1fr); }
.category-options { width: 100%; }
.category-options :deep(.el-radio-button) { flex: 1; }
.category-options :deep(.el-radio-button__inner) { width: 100%; }
.member-add { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; }
.candidate-username { color: var(--text-primary); }
.candidate-real-name { margin-left: 8px; color: var(--text-secondary); font-size: 12px; }
.member-table { display: grid; max-height: 360px; gap: 8px; margin: 16px 0; overflow-y: auto; }
.member-row { display: grid; grid-template-columns: minmax(0, 1fr) 150px auto; align-items: center; gap: 10px; padding: 10px 12px; border: 1px solid var(--border-color); border-radius: var(--radius-md, 10px); }
.member-row-invalid { border-color: var(--color-danger); background: var(--color-danger-bg); }
.member-identity { display: grid; min-width: 0; gap: 3px; }
.member-username { overflow: hidden; color: var(--text-primary); font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.member-real-name { overflow: hidden; color: var(--text-secondary); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.member-invalid { color: var(--color-danger); font-size: 12px; line-height: 1.4; }
.actor-lock { max-width: 150px; color: var(--text-secondary); font-size: 12px; line-height: 1.4; }
.search-result { display: grid; width: 100%; gap: 6px; padding: 14px 4px; border: 0; border-bottom: 1px solid var(--border-color); color: var(--text-primary); background: transparent; cursor: pointer; text-align: left; }
.search-result span { color: var(--text-secondary); font-size: 13px; line-height: 1.6; }
.search-result:focus-visible { outline: 2px solid var(--color-primary); outline-offset: -2px; }
.review-detail { display: grid; gap: 12px; }
.review-meta { color: var(--text-muted-blue); font-size: 13px; }
.review-detail pre { max-height: 55vh; margin: 0; overflow: auto; padding: 22px; border: 1px solid var(--border-color); border-radius: var(--radius-lg, 12px); color: var(--text-primary); background: var(--surface-subtle, #fafafa); font: inherit; line-height: 1.8; white-space: pre-wrap; }
@media (hover: hover) and (pointer: fine) { .search-result:hover { background: var(--color-primary-light); } }
@media (max-width: 900px) { .knowledge-page { height: auto; min-height: calc(100vh - 64px); } .workspace { min-height: 760px; grid-template-columns: minmax(250px, 42vw) minmax(0, 1fr); margin: 8px; } .workspace.collapsed { grid-template-columns: 54px minmax(0, 1fr); } }
@media (max-width: 640px) { .member-add { grid-template-columns: minmax(0, 1fr); } .member-row { grid-template-columns: minmax(0, 1fr); } .actor-lock { max-width: none; } }
@media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto !important; } }
</style>
