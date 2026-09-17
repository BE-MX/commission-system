<template>
  <div class="announcement-page">
    <header class="page-header">
      <div><h1>公告管理</h1><p>发布通知、沉淀知识，重要信息及时送达。</p></div>
      <div class="toolbar">
        <el-button v-any-permission="['announcement:write', 'announcement:admin']" :icon="Plus" type="primary" :disabled="!config.initialized" @click="openEditor(null, true)">新建公告</el-button>
        <el-button :icon="Calendar" :disabled="!config.initialized" @click="weeklyOpen = true">公告周报</el-button>
        <el-button v-permission="'announcement:admin'" :icon="Setting" @click="settingsOpen = true">公告设置</el-button>
      </div>
    </header>
    <el-alert v-if="!config.initialized" type="info" title="公告库尚未初始化，请管理员在公告设置中创建。" :closable="false" />
    <template v-else>
      <el-form inline class="search-form" @submit.prevent="search">
        <el-form-item label="关键词"><el-input v-model="searchForm.q" clearable placeholder="搜索标题或正文" @keyup.enter="search" /></el-form-item>
        <el-form-item label="类别"><el-select v-model="searchForm.category_id" clearable placeholder="全部类别" style="min-width: 160px"><el-option v-for="c in categories" :key="c.id" :label="c.title" :value="c.id" /></el-select></el-form-item>
        <el-form-item label="状态"><el-select v-model="searchForm.status" clearable placeholder="全部状态" style="min-width: 130px"><el-option v-for="(label, value) in statuses" :key="value" :label="label" :value="value" /></el-select></el-form-item>
        <el-form-item><el-button :icon="Search" type="primary" @click="search">查询</el-button><el-button :icon="Refresh" @click="reset">重置</el-button></el-form-item>
      </el-form>
      <div class="table-card">
        <el-table v-loading="loading" :data="list" class="list-table" border>
          <el-table-column label="公告标题" min-width="260" show-overflow-tooltip><template #default="{ row }"><el-button link type="primary" :icon="Document" @click="openEditor(row.id)">{{ row.title }}</el-button></template></el-table-column>
          <el-table-column label="标记" min-width="130"><template #default="{ row }"><el-tag v-if="row.pinned" effect="plain">置顶</el-tag> <el-tag v-if="row.important" effect="plain" type="warning">重要</el-tag></template></el-table-column>
          <el-table-column prop="category_name" label="类别" min-width="130" show-overflow-tooltip />
          <el-table-column label="发布时间" min-width="180"><template #default="{ row }">{{ formatBeijingDateTime(row.published_at) }}</template></el-table-column>
          <el-table-column label="截止时间" min-width="180"><template #default="{ row }">{{ formatBeijingDateTime(row.expires_at) }}</template></el-table-column>
          <el-table-column label="发布状态" min-width="120"><template #default="{ row }"><el-tag effect="plain">{{ statuses[row.status] || row.status }}</el-tag></template></el-table-column>
          <el-table-column label="群推送" min-width="135"><template #default="{ row }">{{ deliveryLabel(row.deliveries) }}</template></el-table-column>
          <el-table-column label="操作" min-width="260" class-name="table-action-column"><template #default="{ row }">
            <el-button link type="primary" :icon="View" @click="openEditor(row.id)">查看</el-button>
            <el-button v-if="row.status !== 'withdrawn'" v-any-permission="['announcement:write', 'announcement:admin', 'knowledge:review']" link type="primary" :icon="Edit" @click="openEditor(row.id, true)">{{ row.pending_approval_id ? '审核详情' : '编辑' }}</el-button>
            <el-button v-permission="'announcement:admin'" link type="primary" :icon="Top" @click="pin(row)">{{ row.pinned ? '取消置顶' : '置顶' }}</el-button>
            <el-button v-if="row.published_at && row.status !== 'withdrawn'" v-permission="'announcement:admin'" link type="danger" :icon="Remove" @click="withdraw(row)">撤回</el-button>
            <el-button v-if="row.status === 'draft' && !row.published_at" v-any-permission="['announcement:write', 'announcement:admin']" link type="danger" :icon="Delete" @click="remove(row)">删除</el-button>
          </template></el-table-column>
        </el-table>
      </div>
      <el-pagination :current-page="page" :page-size="pageSize" :total="total" layout="total, prev, pager, next" @current-change="handlePageChange" />
    </template>
    <DetailDrawer :model-value="editorOpen" :title="editing ? '编辑与审核公告' : '公告详情'" width="min(1120px, 100vw)" @update:model-value="closeEditor">
      <AnnouncementEditor v-if="editorOpen" ref="editor" :key="editorKey" :document-id="selectedId" :edit="editing" :config="config" :categories="categories" @saved="fetchList" />
    </DetailDrawer>
    <el-drawer v-model="settingsOpen" title="公告设置" size="min(850px, 100vw)" destroy-on-close><AnnouncementSettings @updated="load" /></el-drawer>
    <el-drawer v-model="weeklyOpen" title="公告周报" size="min(900px, 100vw)" destroy-on-close><AnnouncementWeekly /></el-drawer>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { Plus, Setting, Calendar, Search, Refresh, Document, View, Edit, Top, Remove, Delete } from '@element-plus/icons-vue'
import { announcementApi as api } from '@/api/announcement'
import { useListPage } from '@/composables/useListPage'
import { formatBeijingDateTime } from '@/utils/datetime'
import { confirmDanger, msgSuccess } from '@/utils/feedback'
import DetailDrawer from '@/components/DetailDrawer.vue'
import AnnouncementEditor from './AnnouncementEditor.vue'
import AnnouncementSettings from './AnnouncementSettings.vue'
import AnnouncementWeekly from './AnnouncementWeekly.vue'
import { deliveryLabel } from './presentation.js'

const route = useRoute(), router = useRouter()
const config = ref({ initialized: false }), categories = ref([])
const settingsOpen = ref(false), weeklyOpen = ref(false), editorOpen = ref(false), editing = ref(false)
const selectedId = ref(null), editorKey = ref(0), editor = ref(null)
const statuses = { draft: '草稿', pending: '待审核', published: '已发布', withdrawn: '已撤回' }
const { list, loading, total, page, pageSize, searchForm, fetchList, handleSearch: search, handleReset: reset, handlePageChange } = useListPage(
  params => api.get('', Object.fromEntries(Object.entries(params).filter(([, v]) => v !== '' && v !== null))),
  { immediate: false, searchForm: { q: '', category_id: null, status: '' } },
)
async function load() {
  config.value = await api.get('/config')
  if (config.value.initialized) { categories.value = await api.get('/categories'); await fetchList() }
}
function openEditor(id, edit = false) { selectedId.value = id; editing.value = edit; editorKey.value++; editorOpen.value = true }
async function mayLeave() {
  if (!editor.value?.hasChanges) return true
  try { await ElMessageBox.confirm('草稿尚未保存，离开会丢失修改。', '未保存的修改', { confirmButtonText: '放弃修改', cancelButtonText: '继续编辑' }); return true }
  catch { return false }
}
async function closeEditor(value) {
  if (value || !(await mayLeave())) return
  editorOpen.value = false
  if (route.params.documentId) router.replace('/announcements')
}
async function pin(row) { await api.put(`/${row.id}/pin`, { pinned: !row.pinned }); await fetchList() }
async function withdraw(row) {
  let reason
  try { reason = (await ElMessageBox.prompt('撤回后将停止展示，并向公告群发送撤回说明。请填写原因。', '撤回公告', { inputPattern: /\S+/, inputErrorMessage: '请填写原因' })).value }
  catch { return }
  await api.post(`/${row.id}/withdraw`, { reason }); await fetchList(); msgSuccess('撤回')
}
async function remove(row) { try { await confirmDanger('删除', row.title) } catch { return }; await api.delete(`/${row.id}`); await fetchList(); msgSuccess('删除') }
function beforeUnload(event) { if (editor.value?.hasChanges) { event.preventDefault(); event.returnValue = '' } }
onBeforeRouteLeave(mayLeave)
onMounted(async () => { window.addEventListener('beforeunload', beforeUnload); await load(); if (route.params.documentId) openEditor(route.params.documentId) })
onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
</script>

<style scoped>
.announcement-page { padding: 24px; display: grid; gap: 20px; }
.page-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
h1 { margin: 0; font-size: 24px; color: var(--text-primary); }
p { margin: 8px 0 0; color: var(--text-secondary); }
.toolbar { display: flex; gap: 10px; flex-wrap: wrap; }
.search-form { padding: 16px 16px 0; background: var(--surface-card); border-radius: 12px; }
@media (max-width: 768px) { .announcement-page { padding: 12px; } }
</style>
