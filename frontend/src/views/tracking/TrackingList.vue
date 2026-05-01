<template>
  <div>
    <!-- 统计卡片 -->
    <div class="stats-banner" v-if="stats">
      <div class="stats-grid">
        <div class="stat-item" @click="filterByStatus('')">
          <div class="stat-value">{{ stats.total }}</div>
          <div class="stat-label">全部运单</div>
        </div>
        <div class="stat-item active" @click="filterByStatus('in_transit')">
          <div class="stat-value">{{ stats.in_transit }}</div>
          <div class="stat-label">运输中</div>
        </div>
        <div class="stat-item" @click="filterByStatus('customs')">
          <div class="stat-value">{{ stats.customs }}</div>
          <div class="stat-label">清关中</div>
        </div>
        <div class="stat-item delivered" @click="filterByStatus('delivered')">
          <div class="stat-value">{{ stats.delivered }}</div>
          <div class="stat-label">已签收</div>
        </div>
        <div class="stat-item warning" @click="filterByStatus('exception')">
          <div class="stat-value">{{ stats.exception }}</div>
          <div class="stat-label">异常</div>
        </div>
      </div>
    </div>

    <!-- 筛选栏 -->
    <el-row :gutter="12" class="toolbar" align="middle">
      <el-col :span="5">
        <el-input v-model="keyword" placeholder="运单号 / 收件人" clearable @keyup.enter="fetchList" @clear="fetchList">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
      </el-col>
      <el-col :span="3">
        <el-select v-model="statusFilter" placeholder="状态" clearable @change="fetchList">
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
        <el-select v-model="activeFilter" placeholder="跟踪状态" clearable @change="fetchList">
          <el-option label="跟踪中" value="1" />
          <el-option label="已结束" value="0" />
        </el-select>
      </el-col>
      <el-col :span="2">
        <GlassButton left-icon="Search" @click="fetchList">查询</GlassButton>
      </el-col>
      <el-col :span="8" style="text-align:right">
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
import { getShipmentList, getTrackingStats, refreshShipment, triggerScanStaging, triggerPoll } from '@/api/tracking'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const { tableRef, maxHeight } = useTableMaxHeight()
const router = useRouter()

const stats = ref(null)
const keyword = ref('')
const statusFilter = ref('')
const carrierFilter = ref('')
const activeFilter = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const tableData = ref([])
const loading = ref(false)

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

function filterByStatus(s) {
  statusFilter.value = s
  fetchList()
}

async function fetchStats() {
  try {
    const res = await getTrackingStats()
    stats.value = res.data
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
      page: page.value,
      page_size: pageSize.value,
    })
    tableData.value = res.data.items
    total.value = res.data.total
  } finally {
    loading.value = false
  }
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

onMounted(() => {
  fetchStats()
  fetchList()
})
</script>

<style scoped>
.toolbar { margin-bottom: 16px; }
.pagination { margin-top: 16px; justify-content: flex-end; }

.stats-banner {
  background: linear-gradient(135deg, #141210 0%, #1E1B18 60%, #141210 100%);
  border-radius: 16px;
  padding: 24px 32px;
  margin-bottom: 16px;
  color: #fff;
}
.stats-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
}
.stat-item {
  background: rgba(255,255,255,0.08);
  border-radius: 10px;
  padding: 16px;
  cursor: pointer;
  transition: background 0.2s;
  text-align: center;
}
.stat-item:hover { background: rgba(255,255,255,0.14); }
.stat-item.active { background: rgba(64,158,255,0.2); }
.stat-item.delivered { background: rgba(103,194,58,0.2); }
.stat-item.warning { background: rgba(245,108,108,0.2); }
.stat-value {
  font-size: 28px;
  font-weight: 700;
  line-height: 1.2;
}
.stat-label {
  font-size: 12px;
  color: rgba(255,255,255,0.65);
  margin-top: 4px;
}
</style>
