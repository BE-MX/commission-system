<template>
  <div>
    <!-- 看板：运单状态概览 -->
    <section class="kanban" v-if="stats">
      <div class="kanban-header">
        <div class="kanban-title">
          <span class="kanban-accent"></span>
          <h3>运单状态概览</h3>
          <span class="kanban-realtime">实时</span>
        </div>
        <span class="kanban-updated" v-if="lastUpdated">
          <el-icon><Clock /></el-icon>
          更新于 {{ lastUpdated }}
        </span>
      </div>

      <div class="kanban-grid">
        <div
          v-for="(item, i) in kanbanItems"
          :key="item.key"
          class="kanban-card"
          :class="{ 'is-active': activeKanban === item.key }"
          :style="{
            background: item.bg,
            borderColor: activeKanban === item.key ? item.color : item.border,
            boxShadow: activeKanban === item.key ? `0 0 0 2px ${item.color}33` : undefined,
            animationDelay: `${i * 70}ms`,
          }"
          @click="handleKanbanClick(item)"
        >
          <div class="kanban-card__bg-icon" :style="{ color: item.color }">
            <el-icon><component :is="item.icon" /></el-icon>
          </div>

          <div class="kanban-card__inner">
            <div class="kanban-card__top">
              <div class="kanban-card__icon" :style="{ background: `${item.color}1f`, color: item.color }">
                <el-icon><component :is="item.icon" /></el-icon>
              </div>
            </div>

            <div class="kanban-card__value">
              <span class="value" :style="{ color: item.color }">{{ getStatValue(item.statKey) }}</span>
              <span class="desc">{{ item.desc }}</span>
            </div>

            <div class="kanban-card__foot">
              <span class="label">{{ item.label }}</span>
              <span class="progress">
                <span class="progress__fill" :style="{ width: `${getProgress(item.statKey)}%`, background: item.color }"></span>
              </span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- 范围选择条 -->
    <div class="scope-bar">
      <el-checkbox v-model="onlyMine" @change="handleOnlyMineChange">
        仅显示我的运单
      </el-checkbox>
      <span class="scope-bar__hint">
        <template v-if="submitter">当前筛选提交人：<b>{{ submitter }}</b></template>
        <template v-else-if="onlyMine">当前仅显示 <b>{{ authStore.user?.real_name || authStore.user?.username || '我' }}</b> 提交的运单</template>
        <template v-else>当前显示全部用户提交的运单</template>
      </span>
    </div>

    <!-- 筛选栏 -->
    <el-row :gutter="12" class="toolbar" align="middle">
      <el-col :span="4">
        <el-input v-model="keyword" placeholder="运单号 / 收件人" clearable @keyup.enter="fetchList" @clear="fetchList">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
      </el-col>
      <el-col :span="3">
        <el-select v-model="statusFilter" placeholder="状态" clearable @change="handleStatusFilterChange">
          <el-option label="待查询" value="pending" />
          <el-option label="运输中" value="in_transit" />
          <el-option label="清关中" value="customs" />
          <el-option label="派送中" value="out_for_delivery" />
          <el-option label="已签收" value="delivered" />
          <el-option label="异常" value="exception" />
          <el-option label="已退回" value="returned" />
        </el-select>
      </el-col>
      <el-col :span="3">
        <el-select v-model="carrierFilter" placeholder="物流商" clearable @change="fetchList">
          <el-option label="DHL" value="DHL" />
          <el-option label="FedEx" value="FEDEX" />
          <el-option label="UPS" value="UPS" />
          <el-option label="TNT" value="TNT" />
        </el-select>
      </el-col>
      <el-col :span="3">
        <el-select
          v-model="submitter"
          placeholder="提交人"
          clearable
          filterable
          @change="handleSubmitterChange"
        >
          <el-option v-for="name in submitters" :key="name" :label="name" :value="name" />
        </el-select>
      </el-col>
      <el-col :span="3">
        <el-select v-model="activeFilter" placeholder="跟踪状态" clearable @change="fetchList">
          <el-option label="跟踪中" value="1" />
          <el-option label="已结束" value="0" />
        </el-select>
      </el-col>
      <el-col :span="2">
        <GlassButton left-icon="Search" @click="fetchList">查询</GlassButton>
      </el-col>
      <el-col :span="6" style="text-align:right">
        <GlassButton left-icon="Refresh" @click="handleScanStaging">扫描暂存</GlassButton>
        <GlassButton left-icon="Loading" @click="handlePoll">批量轮询</GlassButton>
      </el-col>
    </el-row>

    <!-- 表格 -->
    <div class="table-card">
    <el-table
      ref="tableRef"
      :data="tableData"
      v-loading="loading"
      :max-height="maxHeight"
      class="list-table"
      border
    >
      <el-table-column prop="waybill_no" label="运单号" min-width="140" max-width="200" show-overflow-tooltip>
        <template #default="{ row }">
          <GlassButton variant="link" class="primary-link" @click="goDetail(row)">{{ row.waybill_no }}</GlassButton>
        </template>
      </el-table-column>
      <el-table-column prop="carrier_name" label="物流商" min-width="100" max-width="140" show-overflow-tooltip />
      <el-table-column prop="receiver_name" label="收件人" min-width="110" max-width="170" show-overflow-tooltip />
      <el-table-column prop="receiver_company" label="收件公司" min-width="150" max-width="300" show-overflow-tooltip />
      <el-table-column prop="receiver_country" label="国家" min-width="90" max-width="130" show-overflow-tooltip />
      <el-table-column label="状态" min-width="110" max-width="150">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.current_status)" size="small" effect="plain">
            {{ statusText(row.current_status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="current_status_text" label="最新动态" min-width="190" max-width="340" show-overflow-tooltip />
      <el-table-column prop="current_location" label="当前位置" min-width="130" max-width="220" show-overflow-tooltip />
      <el-table-column label="预计送达" min-width="90" max-width="130" show-overflow-tooltip>
        <template #default="{ row }">
          {{ row.estimated_delivery_date ? fmtDateShort(row.estimated_delivery_date) : '-' }}
        </template>
      </el-table-column>
      <el-table-column label="最新时间" min-width="160" max-width="200" show-overflow-tooltip>
        <template #default="{ row }">{{ row.last_event_time || '-' }}</template>
      </el-table-column>
      <el-table-column prop="dingtalk_user_name" label="提交人" min-width="100" max-width="140" show-overflow-tooltip />
      <el-table-column label="短链接" min-width="100" max-width="140">
        <template #default="{ row }">
          <GlassButton v-if="row.short_link" variant="link" left-icon="CopyDocument" @click="copyLink(row.short_link)">
            复制
          </GlassButton>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column label="跟踪" min-width="110" max-width="150">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small" effect="plain">
            {{ row.is_active ? '进行中' : '已结束' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" min-width="90" max-width="130" fixed="right">
        <template #default="{ row }">
          <GlassButton variant="link" left-icon="Refresh" @click="handleRefresh(row)">
            刷新
          </GlassButton>
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
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getShipmentList, getTrackingStats, getSubmitters, refreshShipment, triggerScanStaging, triggerPoll } from '@/api/tracking'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'
import { useAuthStore } from '@/stores/auth'

const { tableRef, maxHeight } = useTableMaxHeight()
const router = useRouter()
const authStore = useAuthStore()

const stats = ref(null)
const lastUpdated = ref('')
const activeKanban = ref('')
const keyword = ref('')
const statusFilter = ref('')
const carrierFilter = ref('')
const activeFilter = ref('')
const onlyMine = ref(true)
const submitter = ref('')
const submitters = ref([])
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const tableData = ref([])
const loading = ref(false)

const kanbanItems = [
  {
    key: 'total', statKey: 'total', statusValue: '',
    label: '全部运单', desc: '累计',
    icon: 'Box', color: '#2563eb',
    bg: 'linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%)', border: '#bfdbfe',
  },
  {
    key: 'in_transit', statKey: 'in_transit', statusValue: 'in_transit',
    label: '运输中', desc: '在途',
    icon: 'Van', color: '#d97706',
    bg: 'linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%)', border: '#fde68a',
  },
  {
    key: 'customs', statKey: 'customs', statusValue: 'customs',
    label: '清关中', desc: '等待放行',
    icon: 'Ship', color: '#7c3aed',
    bg: 'linear-gradient(135deg, #f5f3ff 0%, #ede9fe 100%)', border: '#ddd6fe',
  },
  {
    key: 'delivered', statKey: 'delivered', statusValue: 'delivered',
    label: '已签收', desc: '已完成',
    icon: 'CircleCheck', color: '#059669',
    bg: 'linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%)', border: '#a7f3d0',
  },
  {
    key: 'exception', statKey: 'exception', statusValue: 'exception',
    label: '异常', desc: '需关注',
    icon: 'Warning', color: '#dc2626',
    bg: 'linear-gradient(135deg, #fef2f2 0%, #fee2e2 100%)', border: '#fecaca',
  },
]

function getStatValue(key) {
  return stats.value?.[key] ?? 0
}

function getProgress(key) {
  const totalCount = stats.value?.total || 0
  if (key === 'total') return totalCount > 0 ? 100 : 0
  if (!totalCount) return 0
  const v = stats.value?.[key] || 0
  return Math.min(Math.round((v / totalCount) * 100), 100)
}

function handleKanbanClick(item) {
  if (activeKanban.value === item.key) {
    activeKanban.value = ''
    statusFilter.value = ''
  } else {
    activeKanban.value = item.key
    statusFilter.value = item.statusValue
  }
  page.value = 1
  fetchList()
}

function formatUpdatedAt(d = new Date()) {
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const STATUS_MAP = {
  pending: '待查询',
  picked_up: '已揽收',
  in_transit: '运输中',
  out_for_delivery: '派送中',
  customs: '清关中',
  customs_hold: '海关扣留',
  delivered: '已签收',
  returned: '已退回',
  exception: '异常',
}
const STATUS_TAG = {
  pending: 'info',
  picked_up: '',
  in_transit: '',
  out_for_delivery: 'warning',
  customs: 'warning',
  customs_hold: 'danger',
  delivered: 'success',
  returned: 'danger',
  exception: 'danger',
}

function statusText(s) { return STATUS_MAP[s] || s }
function statusTagType(s) { return STATUS_TAG[s] || 'info' }

// 状态下拉变更时，同步看板高亮（'total' 卡仅由点击触发，不随空筛选自动激活）
function handleStatusFilterChange() {
  const val = statusFilter.value
  if (!val) {
    activeKanban.value = ''
  } else {
    const hit = kanbanItems.find((it) => it.statusValue === val)
    activeKanban.value = hit ? hit.key : ''
  }
  page.value = 1
  fetchList()
}

async function fetchStats() {
  try {
    const res = await getTrackingStats({
      mine: onlyMine.value ? '1' : '',
      submitter: submitter.value,
    })
    stats.value = res.data
    lastUpdated.value = formatUpdatedAt()
  } catch { /* ignore */ }
}

async function fetchSubmitters() {
  try {
    const res = await getSubmitters()
    submitters.value = res.data || []
  } catch { /* ignore */ }
}

async function fetchList() {
  loading.value = true
  try {
    const res = await getShipmentList({
      keyword: keyword.value,
      status: statusFilter.value,
      carrier: carrierFilter.value,
      is_active: activeFilter.value,
      mine: onlyMine.value ? '1' : '',
      submitter: submitter.value,
      page: page.value,
      page_size: pageSize.value,
    })
    tableData.value = res.data.items
    total.value = res.data.total
  } finally {
    loading.value = false
  }
}

function handleOnlyMineChange(val) {
  if (val) {
    submitter.value = ''
  }
  page.value = 1
  fetchList()
  fetchStats()
}

function handleSubmitterChange(val) {
  if (val) {
    onlyMine.value = false
  }
  page.value = 1
  fetchList()
  fetchStats()
}

async function handleRefresh(row) {
  try {
    await refreshShipment(row.waybill_no)
    ElMessage.success('刷新完成')
    fetchList()
    fetchStats()
  } catch { /* handled by interceptor */ }
}

async function handleScanStaging() {
  try {
    const res = await triggerScanStaging()
    const d = res.data
    ElMessage.success(`扫描完成：${d.success} 新增，${d.duplicate} 重复，${d.error} 异常`)
    fetchList()
    fetchStats()
  } catch { /* handled by interceptor */ }
}

async function handlePoll() {
  try {
    const res = await triggerPoll()
    const d = res.data
    ElMessage.success(`轮询完成：${d.total} 条，成功 ${d.ok}，失败 ${d.error}`)
    fetchList()
    fetchStats()
  } catch { /* handled by interceptor */ }
}

function goDetail(row) {
  router.push(`/tracking/${row.waybill_no}`)
}

function copyLink(link) {
  navigator.clipboard.writeText(link).then(() => {
    ElMessage.success('短链接已复制')
  })
}

function fmtDateShort(dateStr) {
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return '-'
  const m = d.getMonth() + 1
  const day = d.getDate()
  return `${m}/${day}`
}

onMounted(() => {
  fetchStats()
  fetchList()
  fetchSubmitters()
})
</script>

<style scoped>
.toolbar { margin-bottom: 16px; }
.pagination { margin-top: 16px; justify-content: flex-end; }

/* ===== 范围选择条 ===== */
.scope-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 12px;
  margin-bottom: 10px;
  background: rgba(212, 148, 28, 0.06);
  border: 1px solid rgba(212, 148, 28, 0.18);
  border-radius: 8px;
}
.scope-bar :deep(.el-checkbox__label) {
  font-size: 13px;
  font-weight: 500;
  color: #374151;
}
.scope-bar__hint {
  font-size: 12px;
  color: #6b7280;
}
.scope-bar__hint b {
  color: #B8860B;
  font-weight: 600;
}

/* ===== 看板：运单状态概览 ===== */
.kanban {
  margin-bottom: 14px;
}
.kanban-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 0 2px 8px;
}
.kanban-title {
  display: flex;
  align-items: center;
  gap: 6px;
}
.kanban-title h3 {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: #1f2937;
  letter-spacing: 0.2px;
}
.kanban-accent {
  width: 3px;
  height: 14px;
  border-radius: 2px;
  background: linear-gradient(180deg, #D4941C 0%, #B8860B 100%);
}
.kanban-realtime {
  font-size: 10px;
  color: #6b7280;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 999px;
  padding: 1px 8px;
  line-height: 14px;
}
.kanban-updated {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  color: #9ca3af;
}
.kanban-updated .el-icon {
  font-size: 11px;
}

.kanban-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
}

.kanban-card {
  position: relative;
  overflow: hidden;
  border: 1px solid;
  border-radius: 10px;
  padding: 10px 12px;
  cursor: pointer;
  transition: transform 0.25s ease, box-shadow 0.25s ease, border-color 0.25s ease;
  opacity: 0;
  transform: translateY(10px);
  animation: kanbanIn 0.4s ease forwards;
}
.kanban-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.08);
}
.kanban-card.is-active {
  transform: translateY(-2px) scale(1.01);
}

@keyframes kanbanIn {
  from { opacity: 0; transform: translateY(10px); }
  to   { opacity: 1; transform: translateY(0); }
}

.kanban-card__bg-icon {
  position: absolute;
  right: -6px;
  bottom: -8px;
  opacity: 0.07;
  transition: transform 0.3s ease, opacity 0.3s ease;
  pointer-events: none;
}
.kanban-card__bg-icon .el-icon {
  font-size: 54px;
}
.kanban-card:hover .kanban-card__bg-icon {
  transform: scale(1.08) rotate(3deg);
  opacity: 0.1;
}

.kanban-card__inner {
  position: relative;
  z-index: 1;
}
.kanban-card__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.kanban-card__icon {
  width: 24px;
  height: 24px;
  border-radius: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.25s ease;
}
.kanban-card__icon .el-icon {
  font-size: 13px;
}
.kanban-card:hover .kanban-card__icon {
  transform: scale(1.08);
}

.kanban-card__value {
  display: flex;
  align-items: baseline;
  gap: 5px;
  margin-bottom: 4px;
}
.kanban-card__value .value {
  font-size: 20px;
  font-weight: 700;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  letter-spacing: -0.4px;
  line-height: 1.1;
}
.kanban-card__value .desc {
  font-size: 10px;
  color: #6b7280;
}

.kanban-card__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}
.kanban-card__foot .label {
  font-size: 11px;
  font-weight: 500;
  color: #374151;
}
.kanban-card__foot .progress {
  width: 32px;
  height: 3px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.6);
  overflow: hidden;
  flex-shrink: 0;
}
.kanban-card__foot .progress__fill {
  display: block;
  height: 100%;
  border-radius: inherit;
  transition: width 0.6s ease;
}
</style>
