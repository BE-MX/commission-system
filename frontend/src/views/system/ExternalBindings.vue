<template>
  <div class="external-bindings">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="bindings-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <div class="page-header">
      <h2>外部账号绑定候选</h2>
      <p>系统自动发现的未绑定外部账号，管理员可在此快速绑定到方舟用户。</p>
    </div>

    <div ref="panelRef" class="table-card bindings-panel">
      <FilterBar :loading="loading" :pending="hasPendingSearch" @search="handleSearch" @reset="resetFilters">
        <el-radio-group v-model="statusFilter">
          <el-radio-button label="">全部</el-radio-button>
          <el-radio-button label="pending">待处理</el-radio-button>
          <el-radio-button label="bound">已绑定</el-radio-button>
          <el-radio-button label="ignored">已忽略</el-radio-button>
        </el-radio-group>
      </FilterBar>

      <div class="action-bar">
        <GlassButton v-permission="'external_binding:write'" variant="primary" left-icon="Connection" :loading="syncingOkki" @click="handleSyncOkki">同步 OKKI 用户</GlassButton>
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          :loading="loading" @refresh="reloadRows"
          @fullscreen="toggleFullscreen"
        />
      </div>

      <ListPageStatus v-if="hasData && errorMessage" :error="errorMessage" :loading="loading" :has-data="hasData" :data-page="dataPage" @retry="reloadRows" />
      <el-table :data="candidates" v-loading="loading" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640">
        <template #empty><ListPageStatus :error="errorMessage" :loading="loading" @retry="reloadRows">
          <el-empty :image-size="96" :description="hasActiveFilters ? '没有符合条件的记录' : '暂无数据'">
            <GlassButton v-if="hasActiveFilters" left-icon="RefreshLeft" @click="resetFilters">重置筛选</GlassButton>
          </el-empty>
        </ListPageStatus></template>
        <el-table-column v-if="visibleKeys.includes('platform')" label="平台" min-width="120" max-width="180">
          <template #default="{ row }">{{ providerLabel(row.provider) }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('external-account-id')" label="外部账号 ID" prop="external_account_id" min-width="140" max-width="210" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('display-name')" label="显示名" prop="external_display_name" min-width="140" max-width="210" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('status')" label="状态" min-width="110" max-width="150">
          <template #default="{ row }">
            <StatusBadge :type="candidateStatusType(row.candidate_status)" size="small" effect="plain">
              {{ candidateStatusLabel(row.candidate_status) }}
            </StatusBadge>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('suggested-user')" label="建议用户" min-width="120" max-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.suggested_user_name">{{ row.suggested_user_name }}</span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('first-seen-at')" label="首次发现" min-width="160" max-width="240" show-overflow-tooltip>
          <template #default="{ row }">{{ formatTime(row.first_seen_at) }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('seen-count')" label="出现次数" prop="seen_count" min-width="90" max-width="135" />
        <el-table-column class-name="table-action-column" label="操作" min-width="200" max-width="300" fixed="right">
          <template #default="{ row }">
            <template v-if="row.candidate_status === 'pending'">
              <GlassButton v-permission="'external_binding:write'" variant="link" left-icon="Connection" @click="openBindDialog(row)">绑定用户</GlassButton>
              <GlassButton link-tone="danger" v-permission="'external_binding:write'" variant="link" left-icon="Close" @click="handleIgnore(row)">忽略</GlassButton>
            </template>
            <span v-else class="text-muted">{{ candidateStatusLabel(row.candidate_status) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 绑定弹窗 -->
    <el-dialog v-model="bindDialogVisible" title="绑定到方舟用户" width="480px" :close-on-click-modal="false">
      <p style="margin-top: 0; color: #909399; font-size: 13px">
        将 <strong>{{ currentCandidate?.external_display_name }}</strong>
        ({{ currentCandidate?.external_account_id }}) 绑定到方舟用户：
      </p>
      <el-select v-model="selectedUserId" filterable remote reserve-keyword placeholder="搜索用户..."
        :remote-method="searchUsers" :loading="searchLoading" style="width: 100%">
        <el-option v-for="u in userOptions" :key="u.id" :label="`${u.real_name} (${u.username})`" :value="u.id" />
      </el-select>
      <ListPageStatus v-if="userResource.error.value" :paged="false" :error="userResource.errorMessage.value" :loading="searchLoading" :has-data="userResource.hasData.value" @retry="searchUsers(userQuery)" />
      <template #footer>
        <GlassButton variant="ghost" @click="bindDialogVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :disabled="!selectedUserId" @click="handleBind">确认绑定</GlassButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { useAsyncResource } from '@/composables/useAsyncResource'
import { useListPage } from '@/composables/useListPage'
import { toRef } from 'vue'
import { msgSuccessText, msgError, confirmAction } from '@/utils/feedback'
import { computed, ref, watch } from 'vue'

// 统一 client：token 注入 / 401 跳转 / 错误提示由拦截器处理（宪法 11）
import { adminClient as authApi } from '@/api/clients'
import { formatBeijingDateTime } from '@/utils/datetime'
import { useTableView } from '@/composables/useTableView'
import TableTools from '@/components/TableTools.vue'

// 列显隐元数据（TableTools 面板数据源，不驱动列渲染）
const columnDefs = [
  { key: 'platform', label: '平台' },
  { key: 'external-account-id', label: '外部账号 ID' },
  { key: 'display-name', label: '显示名' },
  { key: 'status', label: '状态' },
  { key: 'suggested-user', label: '建议用户' },
  { key: 'first-seen-at', label: '首次发现' },
  { key: 'seen-count', label: '出现次数' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useTableView('external-bindings', columnDefs)

const listState = useListPage(async ({ status }, { signal }) => {
  const response = await authApi.get('/external-binding-candidates', { params: status ? { status } : {}, signal, suppressToast: true })
  const items = response.data || []
  return { items, total: items.length }
}, { searchForm: { status: '' } })
const { loading, list: candidates, searchForm, appliedSearchForm, errorMessage, hasData, dataPage, hasPendingSearch, handleSearch, handleReset: resetFilters } = listState
const statusFilter = toRef(searchForm, 'status')
const loadCandidates = listState.refreshUpdate
const reloadRows = () => listState.fetchList()
const hasActiveFilters = computed(() => Boolean(appliedSearchForm.value.status))

const bindDialogVisible = ref(false)
const currentCandidate = ref(null)
const selectedUserId = ref(null)
const userResource = useAsyncResource(async (query, { signal }) =>
  (await authApi.get('/users/list', { params: { keyword: query, page: 1, page_size: 20 }, signal, suppressToast: true, showLoading: false })).data?.items || [], { initialData: [] })
const userOptions = userResource.data, searchLoading = userResource.loading
const userQuery = ref('')
watch(bindDialogVisible, () => { userResource.clear(); userQuery.value = '' }, { flush: 'sync' })
const syncingOkki = ref(false)

async function handleSyncOkki() {
  syncingOkki.value = true
  try {
    const res = await authApi.post('/external-binding-candidates/sync-okki')
    msgSuccessText(res.message || '同步完成')
    loadCandidates()
  } catch (e) {
    // 拦截器已统一提示
  } finally {
    syncingOkki.value = false
  }
}


function searchUsers(query = '') {
  userQuery.value = query
  if (!query || !bindDialogVisible.value) { userResource.clear(); return Promise.resolve(false) }
  return userResource.load(query)
}

function openBindDialog(candidate) {
  userResource.clear(); bindDialogVisible.value = true
  currentCandidate.value = candidate
  selectedUserId.value = candidate.suggested_user_id || null
  if (candidate.suggested_user_id) {
    userOptions.value = candidate.suggested_user_name
      ? [{ id: candidate.suggested_user_id, real_name: candidate.suggested_user_name, username: '' }]
      : []
  } else {
    userOptions.value = []
  }
}

async function handleBind() {
  if (!currentCandidate.value || !selectedUserId.value) return
  try {
    await authApi.post(`/external-binding-candidates/${currentCandidate.value.id}/bind`, null, {
      params: { user_id: selectedUserId.value },
    })
    msgSuccessText('绑定成功')
    bindDialogVisible.value = false
    await loadCandidates()
  } catch { /* 拦截器已统一提示 */ }
}

async function handleIgnore(candidate) {
  try {
    await confirmAction('确认忽略该候选？', '提示', { type: 'warning' })
    await authApi.post(`/external-binding-candidates/${candidate.id}/ignore`)
    msgSuccessText('已忽略')
    await loadCandidates()
  } catch { /* cancelled */ }
}

function providerLabel(p) {
  return { alibaba_icbu: '阿里国际站', okki: 'OKKI', dingtalk: '钉钉', email: '邮箱' }[p] || p
}
function candidateStatusLabel(s) {
  return { pending: '待处理', bound: '已绑定', ignored: '已忽略' }[s] || s
}
function candidateStatusType(s) {
  return { pending: 'warning', bound: 'success', ignored: 'info' }[s] || 'info'
}
function formatTime(t) {
  return formatBeijingDateTime(t)
}


</script>

<style scoped>
/* 极光层（.lg-aurora，与工作台同源）定位上下文 */
.external-bindings {
  padding: 24px 28px;
  position: relative;
}

/* 极光外溢一圈，盖住 main-content 的 24/28 padding 环（同工作台） */
.bindings-aurora {
  inset: -24px -28px;
}

/* 内容压到极光之上。必须点名内容块，不能用 > :not(.lg-aurora)——
   el-dialog 默认就地渲染，通配会覆盖 .el-overlay 的 position: fixed */
.external-bindings .page-header,
.external-bindings .bindings-panel {
  position: relative;
  z-index: 1;
}

.page-header { margin-bottom: 16px; }
.page-header h2 { margin: 0; font-size: 20px; font-family: var(--font-display); color: var(--text-primary); }
.page-header p { margin: 4px 0 0; color: var(--text-muted); font-size: 13px; }
.text-muted { color: var(--text-muted); }

/* 表格面板：同款渐变玻璃（scoped 覆盖全局 .table-card 的白底） */
.bindings-panel {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
}

/* 表格融进玻璃：行/表头半透明，透出极光；hover 用更实的白 */
.bindings-panel :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}

/* 右侧固定操作列：磨砂但不透明的暖白，表头/hover 态同步 */
.bindings-panel :deep(.el-table-fixed-column--right) {
  background-color: rgba(249, 244, 234, 0.97);
}
.bindings-panel :deep(th.el-table-fixed-column--right) {
  background-color: rgba(246, 239, 226, 0.98);
}
.bindings-panel :deep(.el-table__body tr:hover > td.el-table-fixed-column--right) {
  background-color: rgba(245, 236, 220, 0.98);
}
</style>
