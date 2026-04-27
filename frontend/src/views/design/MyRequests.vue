<template>
  <div>
    <!-- 筛选栏 -->
    <el-row :gutter="12" class="toolbar" align="middle">
      <el-col :span="5">
        <el-input
          v-model="keyword"
          placeholder="预约编号 / 客户名"
          clearable
          @keyup.enter="fetchList"
          @clear="fetchList"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
      </el-col>
      <el-col :span="5">
        <el-select
          v-model="statusFilter"
          placeholder="状态筛选"
          clearable
          multiple
          collapse-tags
          @change="fetchList"
        >
          <el-option
            v-for="item in STATUS_OPTIONS"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
      </el-col>
      <el-col :span="2">
        <el-button type="primary" @click="fetchList">
          <el-icon><Search /></el-icon> 查询
        </el-button>
      </el-col>
    </el-row>

    <!-- 表格 -->
    <el-table
      ref="tableRef"
      :data="tableData"
      v-loading="loading"
      stripe
      border
      :max-height="maxHeight"
    >
      <el-table-column prop="request_no" label="预约编号" width="160" show-overflow-tooltip>
        <template #default="{ row }">
          <el-button link type="primary" @click="toggleDetail(row)">{{ row.request_no }}</el-button>
        </template>
      </el-table-column>
      <el-table-column prop="customer_name" label="客户名称" width="140" show-overflow-tooltip />
      <el-table-column label="拍摄类型" width="100">
        <template #default="{ row }">{{ shootTypeLabel(row.shoot_type) }}</template>
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
      <el-table-column label="状态" width="110" align="center">
        <template #default="{ row }">
          <el-tag :type="STATUS_TAG[row.status]" size="small" effect="plain">
            {{ STATUS_MAP[row.status] || row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="170" show-overflow-tooltip />
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="canCancel(row.status)"
            link
            type="danger"
            size="small"
            @click="handleCancel(row)"
          >取消</el-button>
          <el-button link type="primary" size="small" @click="toggleDetail(row)">详情</el-button>
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

    <!-- Detail drawer -->
    <el-drawer v-model="detailVisible" title="预约详情" size="480px" direction="rtl">
      <template v-if="currentDetail">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="预约编号">{{ currentDetail.request_no }}</el-descriptions-item>
          <el-descriptions-item label="客户名称">{{ currentDetail.customer_name }}</el-descriptions-item>
          <el-descriptions-item label="业务员">{{ currentDetail.salesperson_name }}</el-descriptions-item>
          <el-descriptions-item label="拍摄类型">{{ shootTypeLabel(currentDetail.shoot_type) }}</el-descriptions-item>
          <el-descriptions-item label="期望日期">{{ currentDetail.expect_start_date }} ~ {{ currentDetail.expect_end_date }}</el-descriptions-item>
          <el-descriptions-item label="优先级">
            <el-tag :type="currentDetail.priority === 'urgent' ? 'danger' : 'info'" size="small">
              {{ currentDetail.priority === 'urgent' ? '加急' : '普通' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="STATUS_TAG[currentDetail.status]" size="small">
              {{ STATUS_MAP[currentDetail.status] || currentDetail.status }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="备注">{{ currentDetail.remark || '-' }}</el-descriptions-item>
        </el-descriptions>

        <div class="timeline-section">
          <h4>审批记录</h4>
          <el-timeline v-if="auditLogs.length">
            <el-timeline-item
              v-for="log in auditLogs"
              :key="log.id"
              :timestamp="log.created_at"
              placement="top"
              :type="timelineType(log.action)"
            >
              <p class="log-action">{{ log.operator_name }} - {{ LOG_ACTION_MAP[log.action] || log.action }}</p>
              <p class="log-comment" v-if="log.comment">{{ log.comment }}</p>
            </el-timeline-item>
          </el-timeline>
          <el-empty v-else description="暂无审批记录" :image-size="60" />
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getRequests, actionRequest, getAuditLogs } from '@/api/design'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const { tableRef, maxHeight } = useTableMaxHeight()

const keyword = ref('')
const statusFilter = ref([])
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const tableData = ref([])
const loading = ref(false)

const detailVisible = ref(false)
const currentDetail = ref(null)
const auditLogs = ref([])

const SHOOT_TYPE_MAP = {
  product_photo: '产品图',
  model_photo: '模特图',
  video: '视频',
  product_video: '产品视频',
  other: '其他',
}
function shootTypeLabel(t) { return SHOOT_TYPE_MAP[t] || t }

const STATUS_MAP = {
  pending_audit: '待审批',
  pending_design: '待排期',
  scheduled: '已排期',
  in_progress: '进行中',
  completed: '已完成',
  rejected: '已拒绝',
  cancelled: '已取消',
}
const STATUS_TAG = {
  pending_audit: 'warning',
  pending_design: 'warning',
  scheduled: '',
  in_progress: '',
  completed: 'success',
  rejected: 'danger',
  cancelled: 'info',
}
const STATUS_OPTIONS = Object.entries(STATUS_MAP).map(([value, label]) => ({ value, label }))

const LOG_ACTION_MAP = {
  submit: '提交预约',
  approve: '审批通过',
  reject: '审批拒绝',
  confirm: '确认排期',
  start: '开始执行',
  complete: '完成',
  cancel: '取消',
}

function timelineType(action) {
  const map = { approve: 'success', reject: 'danger', cancel: 'info', complete: 'success' }
  return map[action] || 'primary'
}

function canCancel(status) {
  return ['pending_audit', 'pending_design', 'scheduled'].includes(status)
}

async function fetchList() {
  loading.value = true
  try {
    const res = await getRequests({
      keyword: keyword.value || undefined,
      status: statusFilter.value.length ? statusFilter.value.join(',') : undefined,
      page: page.value,
      page_size: pageSize.value,
      operator_id: 1,
      operator_role: 'salesperson',
    })
    tableData.value = res.data?.items || res.data || []
    total.value = res.data?.total || 0
  } finally {
    loading.value = false
  }
}

async function handleCancel(row) {
  try {
    await ElMessageBox.confirm('确定取消该预约？取消后不可恢复。', '确认取消', { type: 'warning' })
  } catch { return }

  try {
    await actionRequest(row.id, {
      action: 'cancel',
      operator_id: 1,
      operator_name: row.salesperson_name || '业务员',
      operator_role: 'salesperson',
    })
    ElMessage.success('已取消')
    fetchList()
  } catch { /* handled by interceptor */ }
}

async function toggleDetail(row) {
  currentDetail.value = row
  detailVisible.value = true
  try {
    const res = await getAuditLogs(row.id)
    auditLogs.value = res.data || []
  } catch {
    auditLogs.value = []
  }
}

onMounted(() => {
  fetchList()
})
</script>

<style scoped>
.toolbar { margin-bottom: 16px; }
.pagination { margin-top: 16px; justify-content: flex-end; }

.timeline-section {
  margin-top: 24px;
}
.timeline-section h4 {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 12px;
  color: var(--text-primary);
}
.log-action {
  font-size: 13px;
  font-weight: 500;
  margin: 0 0 2px;
}
.log-comment {
  font-size: 12px;
  color: var(--text-secondary);
  margin: 0;
}
</style>
