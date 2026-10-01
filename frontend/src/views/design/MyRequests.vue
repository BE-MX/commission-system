<template>
  <div class="my-requests-page">
    <!-- 金色极光背景（纯装饰；与工作台/发票页同源 styles/liquid-glass.css） -->
    <div class="my-requests-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <!-- 表格 -->
    <div ref="panelRef" class="table-card my-requests-panel">
    <!-- 筛选区（List Page Spec 第 5 节） -->
    <div class="toolbar">
      <el-input
        v-model="keyword"
        placeholder="预约编号 / 客户名"
        clearable
        class="filter-w-md"
        @keyup.enter="doSearch"
        @clear="doSearch"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-select
        v-model="salespersonFilter"
        placeholder="业务员"
        clearable
        filterable
        class="filter-w-sm"
        @change="doSearch"
      >
        <el-option
          v-for="item in salespersonOptions"
          :key="item.value"
          :label="item.label"
          :value="item.value"
        />
      </el-select>
      <el-select
        v-model="statusFilter"
        placeholder="状态筛选"
        clearable
        multiple
        collapse-tags
        class="filter-w-md"
        @change="doSearch"
      >
        <el-option
          v-for="item in STATUS_OPTIONS"
          :key="item.value"
          :label="item.label"
          :value="item.value"
        />
      </el-select>
      <el-date-picker
        v-model="expectDateRange"
        type="daterange"
        range-separator="~"
        start-placeholder="期望日期起"
        end-placeholder="期望日期止"
        value-format="YYYY-MM-DD"
        clearable
        class="filter-w-lg"
        @change="doSearch"
      />
      <GlassButton variant="primary" left-icon="Search" @click="doSearch">
        查询
      </GlassButton>
      <GlassButton left-icon="RefreshLeft" @click="resetFilters">
        重置
      </GlassButton>
    </div>

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

    <el-table
      :data="tableData"
      v-loading="loading"
      class="list-table"
      :class="densityClass"
      border
      :max-height="isFullscreen ? undefined : 640"
      @sort-change="orderSort.onSortChange"
    >
      <template #empty>
        <el-empty :image-size="96" :description="hasActiveFilters ? '没有符合条件的记录' : '暂无数据'">
          <GlassButton v-if="hasActiveFilters" left-icon="RefreshLeft" @click="resetFilters">重置筛选</GlassButton>
        </el-empty>
      </template>
      <el-table-column v-if="visibleKeys.includes('request-no')" prop="request_no" label="预约编号" min-width="160" max-width="240" sortable="custom">
        <template #default="{ row }">
          <GlassButton variant="link" @click="toggleDetail(row)">{{ row.request_no }}</GlassButton>
        </template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('salesperson')" prop="salesperson_name" label="业务员" min-width="100" max-width="140" show-overflow-tooltip />
      <el-table-column v-if="visibleKeys.includes('customer-name')" prop="customer_name" label="客户名称" min-width="140" max-width="210" sortable="custom" show-overflow-tooltip />
      <el-table-column v-if="visibleKeys.includes('customer-level')" prop="customer_level" label="客户等级" min-width="100" max-width="140">
        <template #default="{ row }">
          <span>{{ customerLevelLabel(row.customer_level) }}</span>
        </template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('shoot-type')" label="拍摄类型" min-width="100" max-width="150">
        <template #default="{ row }">{{ shootTypeLabel(row.shoot_type) }}</template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('expect-date')" label="期望日期" min-width="230" max-width="320" prop="expect_start_date" sortable="custom">
        <template #default="{ row }">
          {{ formatDatePeriod(row.expect_start_date, row.expect_start_period) }}
          ~
          {{ formatDatePeriod(row.expect_end_date, row.expect_end_period) }}
        </template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('priority')" label="优先级" min-width="80" max-width="120">
        <template #default="{ row }">
          <el-tag :type="row.priority === 'urgent' ? 'danger' : 'info'" effect="plain">
            {{ row.priority === 'urgent' ? '加急' : '普通' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('status')" label="状态" min-width="110" max-width="170" prop="status" sortable="custom">
        <template #default="{ row }">
          <el-tag :type="STATUS_TAG[row.status]" effect="plain">
            {{ STATUS_MAP[row.status] || row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('remark')" prop="remark" label="备注" min-width="160" max-width="260" show-overflow-tooltip>
        <template #default="{ row }">{{ row.remark || '-' }}</template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('created-at')" prop="created_at" label="创建时间" min-width="170" max-width="260" sortable="custom" show-overflow-tooltip />
      <el-table-column class-name="table-action-column" label="操作" min-width="160" max-width="240" fixed="right">
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

        <!-- 附件列表 -->
        <div class="attachment-section">
          <h4>附件</h4>
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
          <el-empty v-else description="暂无附件" :image-size="40" />
        </div>

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
import { Paperclip, Download, Search } from '@element-plus/icons-vue'
import { getRequests, actionRequest, getAuditLogs, getAttachments, downloadAttachment } from '@/api/design'
import { useAuthStore } from '@/stores/auth'
import { getDictMap, buildDictLabel } from '@/utils/dict'
import TableTools from '@/components/TableTools.vue'
import { useTableSort } from '@/composables/useTableSort'
import { useTableView } from '@/composables/useTableView'

const authStore = useAuthStore()
const orderSort = useTableSort()

// 列配置数组：TableTools 列显隐的数据源（操作列不进配置）
const columnDefs = [
  { key: 'request-no', label: '预约编号' },
  { key: 'salesperson', label: '业务员' },
  { key: 'customer-name', label: '客户名称' },
  { key: 'customer-level', label: '客户等级' },
  { key: 'shoot-type', label: '拍摄类型' },
  { key: 'expect-date', label: '期望日期' },
  { key: 'priority', label: '优先级' },
  { key: 'status', label: '状态' },
  { key: 'remark', label: '备注' },
  { key: 'created-at', label: '创建时间' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } =
  useTableView('my-requests', columnDefs)

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
const attachmentList = ref([])

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
  orderSort.reset()
  fetchList()
}

const hasActiveFilters = computed(() =>
  Boolean(keyword.value || salespersonFilter.value || statusFilter.value.length || expectDateRange.value?.length)
)

function resetFilters() {
  keyword.value = ''
  salespersonFilter.value = null
  statusFilter.value = []
  expectDateRange.value = null
  doSearch()
}

function handleSizeChange() {
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
      ...orderSort.sortParams.value,
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

function formatFileSize(bytes) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

async function toggleDetail(row) {
  currentDetail.value = row
  detailVisible.value = true
  attachmentList.value = []
  try {
    const [logRes, attRes] = await Promise.all([
      getAuditLogs(row.id),
      getAttachments(row.id),
    ])
    auditLogs.value = logRes.data || []
    attachmentList.value = attRes.data || []
  } catch {
    auditLogs.value = []
    attachmentList.value = []
  }
}

onMounted(() => {
  loadShootTypeDict()
  fetchList()
})
</script>

<style scoped src="./my-requests.css"></style>
