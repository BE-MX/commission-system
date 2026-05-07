<template>
  <div>
    <!-- 筛选栏 -->
    <el-row :gutter="12" class="toolbar" align="middle">
      <el-col :span="5">
        <el-input
          v-model="keyword"
          placeholder="预约编号 / 客户名"
          clearable
          @keyup.enter="doSearch"
          @clear="doSearch"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
      </el-col>
      <el-col :span="4">
        <el-select
          v-model="salespersonFilter"
          placeholder="业务员"
          clearable
          filterable
          @change="doSearch"
        >
          <el-option
            v-for="item in salespersonOptions"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
      </el-col>
      <el-col :span="4">
        <el-select
          v-model="statusFilter"
          placeholder="状态筛选"
          clearable
          multiple
          collapse-tags
          @change="doSearch"
        >
          <el-option
            v-for="item in STATUS_OPTIONS"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
      </el-col>
      <el-col :span="6">
        <el-date-picker
          v-model="expectDateRange"
          type="daterange"
          range-separator="~"
          start-placeholder="期望日期起"
          end-placeholder="期望日期止"
          value-format="YYYY-MM-DD"
          clearable
          style="width: 100%"
          @change="doSearch"
        />
      </el-col>
      <el-col :span="2">
        <GlassButton left-icon="Search" @click="doSearch">
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
      <el-table-column prop="salesperson_name" label="业务员" min-width="100" max-width="140" show-overflow-tooltip />
      <el-table-column prop="customer_name" label="客户名称" min-width="140" max-width="210" show-overflow-tooltip />
      <el-table-column prop="customer_level" label="客户等级" min-width="100" max-width="140">
        <template #default="{ row }">
          <span>{{ customerLevelLabel(row.customer_level) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="拍摄类型" min-width="100" max-width="150">
        <template #default="{ row }">{{ shootTypeLabel(row.shoot_type) }}</template>
      </el-table-column>
      <el-table-column label="期望日期" min-width="230" max-width="320">
        <template #default="{ row }">
          {{ formatDatePeriod(row.expect_start_date, row.expect_start_period) }}
          ~
          {{ formatDatePeriod(row.expect_end_date, row.expect_end_period) }}
        </template>
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
      <el-table-column prop="remark" label="备注" min-width="160" max-width="260" show-overflow-tooltip>
        <template #default="{ row }">{{ row.remark || '-' }}</template>
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
          <el-descriptions-item label="业务员">{{ currentDetail.salesperson_name }}</el-descriptions-item>
          <el-descriptions-item label="客户名称">{{ currentDetail.customer_name }}</el-descriptions-item>
          <el-descriptions-item label="客户等级">{{ customerLevelLabel(currentDetail.customer_level) }}</el-descriptions-item>
          <el-descriptions-item label="拍摄类型">{{ shootTypeLabel(currentDetail.shoot_type) }}</el-descriptions-item>
          <el-descriptions-item label="期望日期">
            {{ formatDatePeriod(currentDetail.expect_start_date, currentDetail.expect_start_period) }}
            ~
            {{ formatDatePeriod(currentDetail.expect_end_date, currentDetail.expect_end_period) }}
          </el-descriptions-item>
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
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getRequests, actionRequest, getAuditLogs } from '@/api/design'
import { useAuthStore } from '@/stores/auth'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'
import { getDictMap, buildDictLabel } from '@/utils/dict'

const { tableRef, maxHeight } = useTableMaxHeight()
const authStore = useAuthStore()

const keyword = ref('')
const salespersonFilter = ref(null)
const statusFilter = ref([])
const expectDateRange = ref(null)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const tableData = ref([])
const loading = ref(false)

const detailVisible = ref(false)
const currentDetail = ref(null)
const auditLogs = ref([])

// ── 权限：只看自己还是看全部 ─────────────────────────────
const isSelfOnly = computed(() =>
  authStore.hasPermission('design:write') && !authStore.hasAnyPermission(['design:audit', 'design:manage'])
)

// ── 业务员下拉选项：从已有数据中动态收集 ─────────────────
const salespersonOptions = ref([])
function buildSalespersonOptions(items) {
  const seen = new Set()
  const opts = []
  for (const r of items) {
    if (r.salesperson_id && !seen.has(r.salesperson_id)) {
      seen.add(r.salesperson_id)
      opts.push({ value: r.salesperson_id, label: r.salesperson_name })
    }
  }
  // 合并已有选项（避免分页后消失）
  for (const opt of opts) {
    if (!salespersonOptions.value.find(o => o.value === opt.value)) {
      salespersonOptions.value.push(opt)
    }
  }
}

// ── 时段格式化 ──────────────────────────────────────────
const PERIOD_MAP = { am: '上午', pm: '下午' }
function formatDatePeriod(d, period) {
  if (!d) return '-'
  return period ? `${d} ${PERIOD_MAP[period] || period}` : d
}

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
const customerLevelMap = ref({})
async function loadShootTypeDict() {
  shootTypeMap.value = await getDictMap('shoot_type')
  customerLevelMap.value = await getDictMap('customer_level')
}
function shootTypeLabel(t) { return buildDictLabel(t, shootTypeMap.value) }
function customerLevelLabel(code) {
  if (!code) return '-'
  return customerLevelMap.value[code] || code
}

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

function doSearch() {
  page.value = 1
  fetchList()
}

async function fetchList() {
  loading.value = true
  try {
    const params = {
      keyword: keyword.value || undefined,
      status: statusFilter.value.length ? statusFilter.value.join(',') : undefined,
      page: page.value,
      page_size: pageSize.value,
    }
    // 权限控制：只有 design:write 且没有 audit/manage 权限的人只能看自己
    if (isSelfOnly.value) {
      params.salesperson_id = authStore.user?.id
    } else if (salespersonFilter.value) {
      params.salesperson_id = salespersonFilter.value
    }
    // 期望日期范围
    if (expectDateRange.value?.[0]) params.expect_start_date = expectDateRange.value[0]
    if (expectDateRange.value?.[1]) params.expect_end_date = expectDateRange.value[1]

    const res = await getRequests(params)
    const items = res.data?.items || res.data || []
    tableData.value = items
    total.value = res.data?.total || 0
    buildSalespersonOptions(items)
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
      operator_id: authStore.user?.id || row.salesperson_id,
      operator_name: authStore.user?.real_name || row.salesperson_name,
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
