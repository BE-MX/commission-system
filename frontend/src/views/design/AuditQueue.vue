<template>
  <div>
    <!-- 统计卡片 -->
    <div class="stats-banner">
      <div class="stats-grid">
        <div class="stat-item pending">
          <div class="stat-value">{{ stats.pending }}</div>
          <div class="stat-label">待审批</div>
        </div>
        <div class="stat-item approved">
          <div class="stat-value">{{ stats.today_approved }}</div>
          <div class="stat-label">今日通过</div>
        </div>
        <div class="stat-item rejected">
          <div class="stat-value">{{ stats.today_rejected }}</div>
          <div class="stat-label">今日拒绝</div>
        </div>
      </div>
    </div>

    <!-- 表格 -->
    <el-table
      ref="tableRef"
      :data="tableData"
      v-loading="loading"
      stripe
      border
      :max-height="maxHeight"
    >
      <el-table-column prop="request_no" label="预约编号" width="160" show-overflow-tooltip />
      <el-table-column prop="customer_name" label="客户名称" width="130" show-overflow-tooltip />
      <el-table-column prop="salesperson_name" label="业务员" width="90" />
      <el-table-column label="拍摄类型" width="100">
        <template #default="{ row }">{{ SHOOT_TYPE_MAP[row.shoot_type] || row.shoot_type }}</template>
      </el-table-column>
      <el-table-column label="期望日期" width="200">
        <template #default="{ row }">{{ row.expect_start_date }} ~ {{ row.expect_end_date }}</template>
      </el-table-column>
      <el-table-column label="优先级" width="80" align="center">
        <template #default="{ row }">
          <el-tag :type="row.priority === 'urgent' ? 'danger' : 'info'" size="small" effect="plain">
            {{ row.priority === 'urgent' ? '加急' : '普通' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="提交时间" width="170" show-overflow-tooltip />
      <el-table-column label="冲突" width="80" align="center">
        <template #default="{ row }">
          <el-popover
            v-if="row.conflict_detail"
            trigger="hover"
            :content="row.conflict_detail"
            placement="top"
            width="260"
          >
            <template #reference>
              <el-tag type="warning" size="small" effect="plain" style="cursor: pointer">有冲突</el-tag>
            </template>
          </el-popover>
          <span v-else class="text-muted">-</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <el-button link type="success" @click="handleApprove(row)"><el-icon><CircleCheck /></el-icon> 通过</el-button>
          <el-button link type="danger" @click="handleReject(row)"><el-icon><CircleClose /></el-icon> 拒绝</el-button>
        </template>
      </el-table-column>
    </el-table>

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
        <el-button @click="approveVisible = false">取消</el-button>
        <el-button type="primary" @click="submitAudit('approve')" :loading="auditing">确认通过</el-button>
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
        <el-button @click="rejectVisible = false">取消</el-button>
        <el-button type="danger" @click="submitAudit('reject')" :loading="auditing">确认拒绝</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { CircleCheck, CircleClose } from '@element-plus/icons-vue'
import { getRequests, auditRequest } from '@/api/design'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const { tableRef, maxHeight } = useTableMaxHeight()

const SHOOT_TYPE_MAP = {
  product_photo: '产品图',
  model_photo: '模特图',
  video: '视频',
  product_video: '产品视频',
  other: '其他',
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

async function fetchList() {
  loading.value = true
  try {
    const res = await getRequests({
      status: 'pending_audit',
      page: page.value,
      page_size: pageSize.value,
      operator_id: 1,
      operator_role: 'supervisor',
    })
    const data = res.data
    tableData.value = data?.items || data || []
    total.value = data?.total || 0

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
  fetchList()
})
</script>

<style scoped>
.toolbar { margin-bottom: 16px; }
.pagination { margin-top: 16px; justify-content: flex-end; }
.text-muted { color: var(--text-secondary); font-size: 12px; }

.stats-banner {
  background: linear-gradient(135deg, var(--sidebar-bg-from) 0%, var(--sidebar-bg-to) 60%, var(--sidebar-bg-from) 100%);
  border-radius: 16px;
  padding: 24px 32px;
  margin-bottom: 16px;
  color: #fff;
}
.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}
.stat-item {
  background: rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  padding: 16px;
  text-align: center;
}
.stat-item.pending { background: var(--color-warning-bg-strong); }
.stat-item.approved { background: var(--color-success-bg-strong); }
.stat-item.rejected { background: var(--color-danger-bg-strong); }
.stat-value {
  font-size: 28px;
  font-weight: 700;
  line-height: 1.2;
}
.stat-label {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.65);
  margin-top: 4px;
}
</style>
