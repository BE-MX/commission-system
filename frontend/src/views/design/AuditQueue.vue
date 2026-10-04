<template>
  <div class="audit-queue-page">
    <!-- 金色极光背景（纯装饰；与工作台/发票页同源 styles/liquid-glass.css） -->
    <div class="audit-queue-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <!-- 统计卡片 -->
    <div class="stats-banner">
      <div class="stats-grid">
        <div class="stat-item pending lg-card">
          <div class="stat-value">{{ stats.pending }}</div>
          <div class="stat-label">待审批</div>
        </div>
        <div class="stat-item lg-card">
          <div class="stat-value">{{ stats.today_approved }}</div>
          <div class="stat-label">今日通过</div>
        </div>
        <div class="stat-item lg-card">
          <div class="stat-value">{{ stats.today_rejected }}</div>
          <div class="stat-label">今日拒绝</div>
        </div>
      </div>
    </div>

    <!-- 表格 -->
    <div ref="panelRef" class="table-card audit-queue-panel">
    <!-- 操作行：TableTools 四图标（Action Bar Spec；本页无主操作按钮，刷新走工具图标） -->
    <div class="action-bar">
      <TableTools
        v-model:visible-keys="visibleKeys"
        v-model:density="density"
        :columns="columnDefs"
        :fullscreen="isFullscreen"
        @refresh="fetchList"
        @fullscreen="toggleFullscreen"
      />
    </div>
    <ListPageStatus v-if="listState.hasData.value" :error="listState.errorMessage.value" :loading="loading" :has-data="true" :data-page="listState.dataPage.value" @retry="fetchList" />
    <ListPageStatus :error="countsResource.errorMessage.value" :loading="countsResource.loading.value" :has-data="!!countsResource.data.value" @retry="countsResource.load()" />
    <el-table
      :data="tableData"
      v-loading="loading"
      border
      class="list-table"
      :class="densityClass"
      :max-height="isFullscreen ? undefined : 640"
      @sort-change="handleSortChange"
    >
      <template #empty>
        <ListPageStatus :error="listState.errorMessage.value" :loading="loading" @retry="fetchList" />
        <el-empty v-if="listState.isEmpty.value" :image-size="96" description="暂无数据" />
      </template>
      <el-table-column sortable="custom" v-if="visibleKeys.includes('request-no')" prop="request_no" label="预约编号" min-width="160" max-width="240" show-overflow-tooltip />
      <el-table-column sortable="custom" v-if="visibleKeys.includes('customer-name')" prop="customer_name" label="客户名称" min-width="130" max-width="200" show-overflow-tooltip />
      <el-table-column sortable="custom" v-if="visibleKeys.includes('customer-level')" prop="customer_level" label="客户等级" min-width="90" max-width="130">
        <template #default="{ row }">{{ customerLevelLabel(row.customer_level) }}</template>
      </el-table-column>
      <el-table-column sortable="custom" v-if="visibleKeys.includes('salesperson')" prop="salesperson_name" label="业务员" min-width="90" max-width="140" show-overflow-tooltip />
      <el-table-column sortable="custom" v-if="visibleKeys.includes('shoot-type')" prop="shoot_type" label="拍摄类型" min-width="120" max-width="180">
        <template #default="{ row }">{{ buildDictLabel(row.shoot_type, shootTypeMap) }}</template>
      </el-table-column>
      <el-table-column sortable="custom" v-if="visibleKeys.includes('expect-date')" label="期望日期" min-width="230" max-width="320" prop="expect_start_date">
        <template #default="{ row }">
          {{ row.expect_start_date }} {{ row.expect_start_period === 'am' ? '上午' : row.expect_start_period === 'pm' ? '下午' : '' }}
          ~
          {{ row.expect_end_date }} {{ row.expect_end_period === 'am' ? '上午' : row.expect_end_period === 'pm' ? '下午' : '' }}
        </template>
      </el-table-column>
      <el-table-column sortable="custom" v-if="visibleKeys.includes('priority')" label="优先级" min-width="100" max-width="120" prop="priority">
        <template #default="{ row }">
          <StatusBadge :type="row.priority === 'urgent' ? 'danger' : 'info'" effect="plain">
            {{ row.priority === 'urgent' ? '加急' : '普通' }}
          </StatusBadge>
        </template>
      </el-table-column>
      <el-table-column sortable="custom" v-if="visibleKeys.includes('remark')" prop="remark" label="备注" min-width="160" max-width="260" show-overflow-tooltip>
        <template #default="{ row }">{{ row.remark || '-' }}</template>
      </el-table-column>
      <el-table-column sortable="custom" v-if="visibleKeys.includes('created-at')" prop="created_at" label="提交时间" min-width="170" max-width="260" show-overflow-tooltip />
      <el-table-column sortable="custom" v-if="visibleKeys.includes('attachments')" prop="attachments" label="附件" min-width="70" max-width="100">
        <template #default="{ row }">
          <GlassButton
            v-if="attachmentCount(row) > 0"
            variant="link"
            left-icon="Paperclip"
            @click="showAttachments(row)"
          >{{ attachmentCount(row) }}</GlassButton>
          <span v-else class="text-muted">-</span>
        </template>
      </el-table-column>
      <el-table-column sortable="custom" v-if="visibleKeys.includes('conflict')" prop="conflict_detail" label="冲突" min-width="110" max-width="120">
        <template #default="{ row }">
          <el-popover
            v-if="row.conflict_detail"
            trigger="hover"
            :content="row.conflict_detail"
            placement="top"
            width="260"
          >
            <template #reference>
              <StatusBadge type="warning" effect="plain" style="cursor: pointer">有冲突</StatusBadge>
            </template>
          </el-popover>
          <span v-else class="text-muted">-</span>
        </template>
      </el-table-column>
      <el-table-column class-name="table-action-column" label="操作" min-width="210" max-width="300" fixed="right">
        <template #default="{ row }">
          <GlassButton variant="link" left-icon="View" @click="openDetail(row)">详情</GlassButton>
          <GlassButton variant="link" link-tone="success" left-icon="CircleCheck" @click="handleApprove(row)">通过</GlassButton>
          <GlassButton variant="link" link-tone="danger" left-icon="CircleClose" @click="handleReject(row)">拒绝</GlassButton>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      class="pager"
      v-model:current-page="page"
      v-model:page-size="pageSize"
      :total="total"
      layout="total, sizes, prev, pager, next"
      :page-sizes="[20, 50, 100]"
      @current-change="fetchList"
      @size-change="handleSizeChange"
    />
    </div>

    <!-- Approve dialog -->
    <el-dialog v-model="approveVisible" title="审批通过" width="480px" :close-on-click-modal="false">
      <el-form label-position="top">
        <el-form-item label="备注">
          <el-input v-model="auditComment" type="textarea" :rows="3" placeholder="选填审批意见" />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="approveVisible = false">取消</GlassButton>
        <GlassButton variant="primary" @click="submitAudit('approve')" :loading="auditing">确认通过</GlassButton>
      </template>
    </el-dialog>

    <!-- Reject dialog -->
    <el-dialog v-model="rejectVisible" title="审批拒绝" width="480px" :close-on-click-modal="false">
      <el-form label-position="top">
        <el-form-item label="原因" required>
          <el-input v-model="auditComment" type="textarea" :rows="3" placeholder="请填写拒绝原因（必填）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="rejectVisible = false">取消</GlassButton>
        <GlassButton variant="danger" @click="submitAudit('reject')" :loading="auditing">确认拒绝</GlassButton>
      </template>
    </el-dialog>

    <!-- Attachment dialog -->
    <el-dialog v-model="attachmentVisible" title="附件列表" width="640px">
      <ListPageStatus :error="attachmentsResource.errorMessage.value" :loading="attachmentsResource.loading.value" :has-data="attachmentList.length > 0" @retry="attachmentsResource.load()" />
      <div v-if="attachmentList.length" class="attachment-list">
        <div v-for="a in attachmentList" :key="a.id" class="attachment-item">
          <el-icon class="attachment-icon"><Paperclip /></el-icon>
          <span class="attachment-name" :title="a.file_name">{{ a.file_name }}</span>
          <span class="attachment-size">{{ formatFileSize(a.file_size) }}</span>
          <a @click.prevent="downloadAttachment(a)" href="javascript:void(0)" class="attachment-download">
            <el-icon><Download /></el-icon>
          </a>
        </div>
      </div>
      <el-empty v-else-if="!attachmentsResource.loading.value && !attachmentsResource.error.value" description="暂无附件" :image-size="60" />
    </el-dialog>

    <!-- 预约详情抽屉 -->
    <RequestDetailDrawer v-model="detailVisible" :request-id="detailRequestId" />
  </div>
</template>

<script setup>import { msgWarning, msgSuccessText } from '@/utils/feedback'
import { ref, reactive, onMounted, computed, watch } from 'vue'
import { useListPage } from '@/composables/useListPage'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { designActorScope, watchDesignActor } from './designListScope'
import { useAuthStore } from '@/stores/auth'


import { CircleCheck, CircleClose, Paperclip, Download } from '@element-plus/icons-vue'
import { getRequests, auditRequest, getAttachments, downloadAttachment } from '@/api/design'
import { getDictMap, buildDictLabel } from '@/utils/dict'
import RequestDetailDrawer from '@/components/design/RequestDetailDrawer.vue'
import TableTools from '@/components/TableTools.vue'
import { useTableSort } from '@/composables/useTableSort'
import { useTableView } from '@/composables/useTableView'

const orderSort = useTableSort()
const authStore = useAuthStore()
const readScope = () => designActorScope(authStore)

// 列配置数组：TableTools 列显隐的数据源（操作列不进配置）
const columnDefs = [
  { key: 'request-no', label: '预约编号' },
  { key: 'customer-name', label: '客户名称' },
  { key: 'customer-level', label: '客户等级' },
  { key: 'salesperson', label: '业务员' },
  { key: 'shoot-type', label: '拍摄类型' },
  { key: 'expect-date', label: '期望日期' },
  { key: 'priority', label: '优先级' },
  { key: 'remark', label: '备注' },
  { key: 'created-at', label: '提交时间' },
  { key: 'attachments', label: '附件' },
  { key: 'conflict', label: '冲突' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } =
  useTableView('audit-queue', columnDefs)

const shootTypeMap = ref({})
const customerLevelMap = ref({})
async function loadShootTypeDict() {
  shootTypeMap.value = await getDictMap('shoot_type')
  customerLevelMap.value = await getDictMap('customer_level')
}
function customerLevelLabel(code) {
  if (!code) return '-'
  return customerLevelMap.value[code] || code
}

const stats = reactive({ pending: 0, today_approved: 0, today_rejected: 0 })
const listState = useListPage(async (params, { signal, isCurrent }) => {
  const response = await getRequests({ ...params, status: 'pending_audit', operator_id: 1, operator_role: 'supervisor' }, { signal, suppressToast: true })
  const data = response.data
  if (isCurrent()) { stats.pending = data?.stats?.pending ?? data?.total ?? 0; stats.today_approved = data?.stats?.today_approved ?? 0; stats.today_rejected = data?.stats?.today_rejected ?? 0 }
  return { items: data?.items || data || [], total: data?.total || 0 }
}, { sortParams: orderSort.sortParams.value })
const page = listState.page; const pageSize = listState.pageSize; const total = listState.total; const tableData = listState.list; const loading = listState.loading
const fetchList = listState.fetchList
const handleSizeChange = listState.handleSizeChange
function handleSortChange(info) { orderSort.onSortChange(info); return listState.handleSortChange(orderSort.sortParams.value) }
const countsResource = useAsyncResource(async (ids, { signal }) => Object.fromEntries(await Promise.all((ids || []).map(async id => [id, ((await getAttachments(id, { signal, suppressToast: true })).data || []).length]))))
watch(tableData, rows => countsResource.load(rows.map(row => row.id), { clear: true }), { flush: 'sync' })
const attachmentCount = row => countsResource.data.value?.[row.id] ?? null
watchDesignActor(listState, readScope, () => { Object.assign(stats, { pending: 0, today_approved: 0, today_rejected: 0 }); detailVisible.value = false; attachmentVisible.value = false; attachmentsResource.load(null, { clear: true }) })

const approveVisible = ref(false)
const rejectVisible = ref(false)
const auditComment = ref('')
const auditing = ref(false)
const currentRow = ref(null)
const attachmentVisible = ref(false)
const attachmentsResource = useAsyncResource(async (id, { signal }) => id ? (await getAttachments(id, { signal, suppressToast: true })).data || [] : [])
const attachmentList = computed(() => attachmentsResource.data.value || [])
const detailVisible = ref(false)
const detailRequestId = ref(null)

function openDetail(row) {
  detailRequestId.value = row.id
  detailVisible.value = true
}

function formatFileSize(bytes) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

async function showAttachments(row) { attachmentVisible.value = true; return attachmentsResource.load(row.id, { clear: true }) }

function handleApprove(row) {
  currentRow.value = row
  auditComment.value = ''
  approveVisible.value = true
}

function handleReject(row) {
  currentRow.value = row
  auditComment.value = ''
  rejectVisible.value = true
}

async function submitAudit(action) {
  if (action === 'reject' && !auditComment.value.trim()) {
    msgWarning('请填写拒绝原因')
    return
  }
  auditing.value = true
  try {
    await auditRequest(currentRow.value.id, {
      action,
      comment: auditComment.value.trim(),
      operator_id: 1,
      operator_name: '管理员',
      operator_role: 'supervisor',
    })
    msgSuccessText(action === 'approve' ? '已通过' : '已拒绝')
    approveVisible.value = false
    rejectVisible.value = false
    listState.refreshUpdate()
  } finally {
    auditing.value = false
  }
}

onMounted(() => {
  loadShootTypeDict()
})
</script>

<style scoped>
/* 极光层（.lg-aurora）定位上下文 */
.audit-queue-page {
  position: relative;
}

/* 极光外溢一圈，盖住 main-content 的 24/28 padding 环 */
.audit-queue-aurora {
  inset: -24px -28px;
}

/* 内容压到极光之上（点名内容块，不能用 > :not(.lg-aurora) 通配——
   会压掉就地渲染的 el-dialog/el-drawer .el-overlay 的 position: fixed） */
.audit-queue-page .stats-banner,
.audit-queue-page .audit-queue-panel {
  position: relative;
  z-index: 1;
}

/* 表格面板：同款渐变玻璃（scoped 覆盖全局 .table-card 的白底） */
.audit-queue-panel {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
  overflow: hidden;
}

/* 表格融进玻璃：行/表头半透明，透出极光；hover 用更实的白 */
.audit-queue-panel :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}

/* 右侧固定操作列：sticky 单元格 + background: inherit，行透明时会透上来重影，
   改成磨砂但不透明的暖白，表头/hover 态同步 */
.audit-queue-panel :deep(.el-table-fixed-column--right) {
  background-color: rgba(249, 244, 234, 0.97);
}
.audit-queue-panel :deep(th.el-table-fixed-column--right) {
  background-color: rgba(246, 239, 226, 0.98);
}
.audit-queue-panel :deep(.el-table__body tr:hover > td.el-table-fixed-column--right) {
  background-color: rgba(245, 236, 220, 0.98);
}

.text-muted { color: var(--text-secondary); font-size: 12px; }

.attachment-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.attachment-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--fill-color-lighter, #fafafa);
  border-radius: 6px;
  font-size: 13px;
}
.attachment-icon {
  color: var(--text-secondary);
  flex-shrink: 0;
}
.attachment-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.attachment-size {
  color: var(--text-secondary);
  font-size: 12px;
  flex-shrink: 0;
}
.attachment-download {
  color: var(--color-primary-text);
  flex-shrink: 0;
  cursor: pointer;
  display: flex;
  align-items: center;
}

.stats-banner {
  margin-bottom: 16px;
}
.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}
/* 玻璃质感由 .lg-card 提供（渐变磨砂 + 暖金彩色阴影 + hover 上浮），这里只留布局 */
.stat-item {
  padding: 16px;
  text-align: center;
}
/* 强调卡（待审批）：金调渐变玻璃（scoped 优先级高于全局 .lg-card，可覆盖其背景/描边） */
.stat-item.pending {
  background: linear-gradient(165deg, rgba(255, 255, 255, 0.8) 0%, rgba(245, 203, 92, 0.16) 100%);
  border-color: rgba(212, 148, 28, 0.4);
}
.stat-value {
  font-size: 28px;
  font-weight: 700;
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}
.stat-label {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 4px;
}
</style>
