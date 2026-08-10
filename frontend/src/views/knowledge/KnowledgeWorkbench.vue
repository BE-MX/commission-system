<template>
  <div class="knowledge-page">
    <header class="page-bar">
      <div class="search-box">
        <el-input v-model="searchQuery" clearable placeholder="搜索已发布知识" @keyup.enter="runSearch">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <GlassButton variant="primary" @click="runSearch">搜索</GlassButton>
      </div>
      <div class="page-actions">
        <GlassButton v-if="capabilities.review" variant="ghost" left-icon="Stamp" @click="openApprovals">审批队列</GlassButton>
        <GlassButton v-if="capabilities.admin && selectedLibrary" variant="ghost" left-icon="User" @click="openMembers">成员权限</GlassButton>
      </div>
    </header>

    <div class="workspace">
      <KnowledgeSidebar
        :libraries="libraries"
        :selected-library-id="selectedLibraryId"
        :tree="nestedTree"
        :can-write="capabilities.write"
        :can-create-library="canCreateLibrary"
        :can-delete-library="canCreateLibrary"
        :can-delete-node="capabilities.deleteNode"
        @select-library="selectLibrary"
        @select-document="selectDocument"
        @create-library="libraryDialog = true"
        @create-node="openNodeDialog"
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

    <el-dialog v-model="memberDialog" title="成员权限" width="620px">
      <el-alert title="POC 使用方舟用户 ID 绑定账号；后续接入组织通讯录后改为姓名搜索。" type="info" show-icon :closable="false" />
      <div class="member-table">
        <div v-for="(member, index) in members" :key="index" class="member-row">
          <el-input-number v-model="member.user_id" :min="1" controls-position="right" />
          <el-select v-model="member.role">
            <el-option label="只读" value="viewer" /><el-option label="编辑" value="editor" />
            <el-option label="审核" value="reviewer" /><el-option label="管理" value="admin" />
          </el-select>
          <GlassButton variant="link" link-tone="danger" @click="members.splice(index, 1)">移除</GlassButton>
        </div>
      </div>
      <GlassButton variant="ghost" left-icon="Plus" @click="members.push({ user_id: null, role: 'viewer' })">添加成员</GlassButton>
      <template #footer>
        <GlassButton variant="ghost" @click="memberDialog = false">取消</GlassButton>
        <GlassButton variant="primary" @click="saveMembers">保存权限</GlassButton>
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
const searchQuery = ref('')
const searchResults = ref([])
const libraryForm = reactive({ name: '', description: '' })
const nodeForm = reactive({ title: '', node_type: 'document' })

const selectedLibrary = computed(() => libraries.value.find(item => item.id === selectedLibraryId.value))
const capabilities = computed(() => capabilitiesFor(selectedLibrary.value?.role))
const canCreateLibrary = computed(() => auth.hasPermission('knowledge:admin'))
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
  const created = unwrap(await knowledgeClient.post('/libraries', libraryForm))
  libraryDialog.value = false
  Object.assign(libraryForm, { name: '', description: '' })
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
  saving.value = true
  try {
    await knowledgeClient.put(`/documents/${document.value.id}`, { title: payload.title, content: payload.content })
    await Promise.all([loadTree(), reloadDocument(document.value.id)])
    await nextTick()
    payload.done()
    msgSuccess('保存')
  } catch (error) {
    payload.fail?.()
    throw error
  } finally { saving.value = false }
}

async function submitDocument() {
  await knowledgeClient.post(`/documents/${document.value.id}/submit`)
  await Promise.all([loadTree(), reloadDocument(document.value.id)])
  msgSuccess('提交审批')
}

async function openMembers() {
  members.value = unwrap(await knowledgeClient.get(`/libraries/${selectedLibraryId.value}/members`))
  memberDialog.value = true
}

async function saveMembers() {
  if (members.value.some(item => !item.user_id)) return msgError('请填写成员用户 ID')
  await knowledgeClient.put(`/libraries/${selectedLibraryId.value}/members`, { members: members.value })
  memberDialog.value = false
  await loadLibraries()
  msgSuccess('保存权限')
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
  if (!searchQuery.value.trim()) return msgError('请输入搜索关键词')
  searchResults.value = unwrap(await knowledgeClient.get('/search', { params: { q: searchQuery.value, limit: 20 } }))
  searchDialog.value = true
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
.page-bar { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 14px 20px; border-bottom: 1px solid var(--border-color); background: rgba(255, 255, 255, .92); backdrop-filter: blur(14px); }
.search-box { display: flex; width: min(520px, 55vw); gap: 8px; }
.page-actions { display: flex; gap: 8px; }
.workspace { display: grid; min-height: 0; flex: 1; grid-template-columns: 300px minmax(0, 1fr); margin: 14px; overflow: hidden; border: 1px solid var(--border-color); border-radius: var(--radius-xl, 16px); background: var(--surface-card, #fff); box-shadow: var(--shadow-card, 0 8px 30px rgba(30, 36, 50, .06)); }
.member-table { display: grid; gap: 8px; margin: 16px 0; }
.member-row { display: grid; grid-template-columns: 180px 1fr auto; gap: 10px; }
.search-result { display: grid; width: 100%; gap: 6px; padding: 14px 4px; border: 0; border-bottom: 1px solid var(--border-color); color: var(--text-primary); background: transparent; cursor: pointer; text-align: left; }
.search-result span { color: var(--text-secondary); font-size: 13px; line-height: 1.6; }
.search-result:focus-visible { outline: 2px solid var(--color-primary); outline-offset: -2px; }
.review-detail { display: grid; gap: 12px; }
.review-meta { color: var(--text-muted-blue); font-size: 13px; }
.review-detail pre { max-height: 55vh; margin: 0; overflow: auto; padding: 22px; border: 1px solid var(--border-color); border-radius: var(--radius-lg, 12px); color: var(--text-primary); background: var(--surface-subtle, #fafafa); font: inherit; line-height: 1.8; white-space: pre-wrap; }
@media (hover: hover) and (pointer: fine) { .search-result:hover { background: var(--color-primary-light); } }
@media (max-width: 900px) { .knowledge-page { height: auto; min-height: calc(100vh - 64px); } .page-bar { align-items: stretch; flex-direction: column; } .search-box { width: 100%; } .workspace { min-height: 760px; grid-template-columns: 240px minmax(0, 1fr); margin: 8px; } }
@media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto !important; } }
</style>
