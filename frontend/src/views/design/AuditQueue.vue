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
    <div class="table-card audit-queue-panel">
    <el-table
      ref="tableRef"
      :data="tableData"
      v-loading="loading"
      border
      class="list-table"
      :max-height="maxHeight"
      @sort-change="orderSort.onSortChange"
    >
      <el-table-column prop="request_no" label="预约编号" min-width="160" max-width="240" sortable="custom" show-overflow-tooltip />
      <el-table-column prop="customer_name" label="客户名称" min-width="130" max-width="200" sortable="custom" show-overflow-tooltip />
      <el-table-column prop="customer_level" label="客户等级" min-width="90" max-width="130">
        <template #default="{ row }">{{ customerLevelLabel(row.customer_level) }}</template>
      </el-table-column>
      <el-table-column prop="salesperson_name" label="业务员" min-width="90" max-width="140" sortable="custom" show-overflow-tooltip />
      <el-table-column label="拍摄类型" min-width="120" max-width="180">
        <template #default="{ row }">{{ buildDictLabel(row.shoot_type, shootTypeMap) }}</template>
      </el-table-column>
      <el-table-column label="期望日期" min-width="230" max-width="320" prop="expect_start_date" sortable="custom">
        <template #default="{ row }">
          {{ row.expect_start_date }} {{ row.expect_start_period === 'am' ? '上午' : row.expect_start_period === 'pm' ? '下午' : '' }}
          ~
          {{ row.expect_end_date }} {{ row.expect_end_period === 'am' ? '上午' : row.expect_end_period === 'pm' ? '下午' : '' }}
        </template>
      </el-table-column>
      <el-table-column label="优先级" min-width="80" max-width="120" prop="priority" sortable="custom">
        <template #default="{ row }">
          <el-tag :type="row.priority === 'urgent' ? 'danger' : 'info'" effect="plain">
            {{ row.priority === 'urgent' ? '加急' : '普通' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="remark" label="备注" min-width="160" max-width="260" show-overflow-tooltip>
        <template #default="{ row }">{{ row.remark || '-' }}</template>
      </el-table-column>
      <el-table-column prop="created_at" label="提交时间" min-width="170" max-width="260" sortable="custom" show-overflow-tooltip />
      <el-table-column label="附件" min-width="70" max-width="100">
        <template #default="{ row }">
          <GlassButton
            v-if="row._attachment_count > 0"
            variant="link"
            left-icon="Paperclip"
            @click="showAttachments(row)"
          >{{ row._attachment_count }}</GlassButton>
          <span v-else class="text-muted">-</span>
        </template>
      </el-table-column>
      <el-table-column label="冲突" min-width="80" max-width="120">
        <template #default="{ row }">
          <el-popover
            v-if="row.conflict_detail"
            trigger="hover"
            :content="row.conflict_detail"
            placement="top"
            width="260"
          >
            <template #reference>
              <el-tag type="warning" effect="plain" style="cursor: pointer">有冲突</el-tag>
            </template>
          </el-popover>
          <span v-else class="text-muted">-</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" min-width="210" max-width="300" fixed="right">
        <template #default="{ row }">
          <GlassButton variant="link" left-icon="View" @click="openDetail(row)">详情</GlassButton>
          <GlassButton variant="link" link-tone="success" left-icon="CircleCheck" @click="handleApprove(row)">通过</GlassButton>
          <GlassButton variant="link" link-tone="danger" left-icon="CircleClose" @click="handleReject(row)">拒绝</GlassButton>
        </template>
      </el-table-column>
    </el-table>
    </div>

    <el-pagination
      class="pagination"
      v-model:current-page="page"
      v-model:page-size="pageSize"
      :total="total"
      layout="total, prev, pager, next, sizes"
      :page-sizes="[20, 50, 100]"
      @current-change="fetchList"
      @size-change="fetchList"
    />

    <!-- Approve dialog -->
    <el-dialog v-model="approveVisible" title="审批通过" width="460px" :close-on-click-modal="false">
      <el-form label-width="80px">
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
    <el-dialog v-model="rejectVisible" title="审批拒绝" width="460px" :close-on-click-modal="false">
      <el-form label-width="80px">
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
    <el-dialog v-model="attachmentVisible" title="附件列表" width="500px">
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
      <el-empty v-else description="暂无附件" :image-size="60" />
    </el-dialog>

    <!-- 预约详情抽屉 -->
    <RequestDetailDrawer v-model="detailVisible" :request-id="detailRequestId" />
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { CircleCheck, CircleClose, Paperclip, Download } from '@element-plus/icons-vue'
import { getRequests, auditRequest, getAttachments, downloadAttachment } from '@/api/design'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'
import { getDictMap, buildDictLabel } from '@/utils/dict'
import RequestDetailDrawer from '@/components/design/RequestDetailDrawer.vue'
import { useTableSort } from '@/composables/useTableSort'

const { tableRef, maxHeight } = useTableMaxHeight()
const orderSort = useTableSort()

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
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const tableData = ref([])
const loading = ref(false)

const approveVisible = ref(false)
const rejectVisible = ref(false)
const auditComment = ref('')
const auditing = ref(false)
const currentRow = ref(null)
const attachmentVisible = ref(false)
const attachmentList = ref([])
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

async function showAttachments(row) {
  attachmentList.value = []
  attachmentVisible.value = true
  try {
    const res = await getAttachments(row.id)
    attachmentList.value = res.data || []
  } catch {
    attachmentList.value = []
  }
}

async function fetchList() {
  loading.value = true
  try {
    const res = await getRequests({
      status: 'pending_audit',
      page: page.value,
      page_size: pageSize.value,
      operator_id: 1,
      operator_role: 'supervisor',
      ...orderSort.sortParams.value,
    })
    const data = res.data
    tableData.value = data?.items || data || []
    total.value = data?.total || 0

    // 并行获取每个预约单的附件数量
    const items = tableData.value
    const countPromises = items.map(row =>
      getAttachments(row.id)
        .then(res => { row._attachment_count = (res.data || []).length })
        .catch(() => { row._attachment_count = 0 })
    )
    Promise.all(countPromises)

    // Update stats from response if available, otherwise count from list
    stats.pending = data?.stats?.pending ?? total.value
    stats.today_approved = data?.stats?.today_approved ?? 0
    stats.today_rejected = data?.stats?.today_rejected ?? 0
  } finally {
    loading.value = false
  }
}

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
    ElMessage.warning('请填写拒绝原因')
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
    ElMessage.success(action === 'approve' ? '已通过' : '已拒绝')
    approveVisible.value = false
    rejectVisible.value = false
    fetchList()
  } finally {
    auditing.value = false
  }
}

onMounted(() => {
  loadShootTypeDict()
  fetchList()
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
.audit-queue-page .audit-queue-panel,
.audit-queue-page .pagination {
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

.toolbar { margin-bottom: 16px; }
.pagination { margin-top: 16px; justify-content: flex-end; }
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
  color: var(--color-primary);
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
