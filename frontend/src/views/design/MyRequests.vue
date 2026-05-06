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
        <GlassButton left-icon="Search" @click="fetchList">
          查询
        </GlassButton>
      </el-col>
    </el-row>

    <!-- 表格 -->
    <div class="table-card">
    <el-table
      ref="tableRef"
      :data="tableData"
      v-loading="loading"
      class="list-table"
      border
      :max-height="maxHeight"
    >
      <el-table-column prop="request_no" label="预约编号" min-width="160" max-width="240">
        <template #default="{ row }">
          <GlassButton variant="link" @click="toggleDetail(row)">{{ row.request_no }}</GlassButton>
        </template>
      </el-table-column>
      <el-table-column prop="customer_name" label="客户名称" min-width="140" max-width="210" show-overflow-tooltip />
      <el-table-column label="拍摄类型" min-width="100" max-width="150">
        <template #default="{ row }">{{ shootTypeLabel(row.shoot_type) }}</template>
      </el-table-column>
      <el-table-column label="期望日期" min-width="200" max-width="300">
        <template #default="{ row }">{{ row.expect_start_date }} ~ {{ row.expect_end_date }}</template>
      </el-table-column>
      <el-table-column label="优先级" min-width="80" max-width="120">
        <template #default="{ row }">
          <el-tag :type="row.priority === 'urgent' ? 'danger' : 'info'" effect="plain">
            {{ row.priority === 'urgent' ? '加急' : '普通' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" min-width="110" max-width="170">
        <template #default="{ row }">
          <el-tag :type="STATUS_TAG[row.status]" effect="plain">
            {{ STATUS_MAP[row.status] || row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" min-width="170" max-width="260" show-overflow-tooltip />
      <el-table-column label="操作" min-width="160" max-width="240" fixed="right">
        <template #default="{ row }">
          <GlassButton variant="link" left-icon="View" @click="toggleDetail(row)">详情</GlassButton>
          <GlassButton
            v-if="canCancel(row.status)"
            variant="link"
            link-tone="danger"
            left-icon="CircleClose"
            @click="handleCancel(row)"
          >取消</GlassButton>
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
              <p class="log-action">{{ LOG_ACTION_MAP[log.action] || log.action }}</p>
              <p class="log-operator">{{ log.operator_name }} ({{ ROLE_MAP[log.operator_role] || log.operator_role }})</p>
              <p class="log-transition" v-if="log.from_status || log.to_status">
                {{ STATUS_MAP[log.from_status] || log.from_status || '-' }} &rarr; {{ STATUS_MAP[log.to_status] || log.to_status || '-' }}
              </p>
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
import { View, CircleClose } from '@element-plus/icons-vue'
import { getRequests, actionRequest, getAuditLogs } from '@/api/design'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'
import { getDictMap, buildDictLabel } from '@/utils/dict'

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

const shootTypeMap = ref({})
async function loadShootTypeDict() {
  shootTypeMap.value = await getDictMap('shoot_type')
}
function shootTypeLabel(t) { return buildDictLabel(t, shootTypeMap.value) }

const LOG_ACTION_MAP = {
  submit: '提交申请',
  approve: '审批通过',
  reject: '驳回',
  confirm: '确认排期',
  start: '开始执行',
  complete: '完成',
  cancel: '取消',
  reschedule: '调整排期',
}

const ROLE_MAP = {
  salesperson: '业务员',
  supervisor: '主管',
  design_staff: '设计部',
}

function timelineType(action) {
  const map = {
    submit: 'primary',
    approve: 'success',
    reject: 'danger',
    confirm: 'primary',
    start: 'warning',
    complete: 'success',
    cancel: 'info',
    reschedule: 'warning',
  }
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
  loadShootTypeDict()
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
  font-weight: 600;
  margin: 0 0 2px;
}
.log-operator {
  font-size: 12px;
  color: var(--text-secondary);
  margin: 0 0 2px;
}
.log-transition {
  font-size: 12px;
  color: var(--color-primary);
  margin: 0 0 2px;
}
.log-comment {
  font-size: 12px;
  color: var(--text-secondary);
  margin: 0;
}
</style>
