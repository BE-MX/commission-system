<template>
  <div>
    <!-- 批次摘要卡片 -->
    <div v-if="summary" class="summary-banner">
      <div class="summary-top">
        <div class="summary-title">{{ summary.batch_name }}</div>
        <el-tag :type="statusType(summary.status)" effect="dark" round size="small">{{ statusLabel(summary.status) }}</el-tag>
      </div>
      <div class="summary-grid">
        <div class="summary-item">
          <div class="summary-label">回款总额</div>
          <div class="summary-value">{{ summary.total_payment_amount?.toFixed(2) }}</div>
        </div>
        <div class="summary-item">
          <div class="summary-label">业务员提成</div>
          <div class="summary-value">{{ summary.total_salesperson_commission?.toFixed(2) }}</div>
        </div>
        <div class="summary-item">
          <div class="summary-label">一级主管提成</div>
          <div class="summary-value">{{ summary.total_supervisor_commission?.toFixed(2) }}</div>
        </div>
        <div class="summary-item">
          <div class="summary-label">二级主管提成</div>
          <div class="summary-value">{{ summary.total_second_supervisor_commission?.toFixed(2) }}</div>
        </div>
        <div class="summary-item highlight">
          <div class="summary-label">总提成</div>
          <div class="summary-value">{{ summary.total_commission?.toFixed(2) }}</div>
        </div>
      </div>
    </div>

    <!-- 筛选栏 -->
    <el-row :gutter="16" class="toolbar">
      <el-col :span="6">
        <el-input v-model="keyword" placeholder="搜索客户/业务员/主管" clearable @keyup.enter="fetchDetails" @clear="fetchDetails">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
      </el-col>
      <el-col :span="2">
        <el-button type="primary" @click="fetchDetails"><el-icon><Search /></el-icon> 查询</el-button>
      </el-col>
      <el-col :span="2">
        <el-button @click="$router.push('/commission/batch')"><el-icon><ArrowLeft /></el-icon> 返回列表</el-button>
      </el-col>
    </el-row>

    <!-- 明细表格 -->
    <el-table ref="tableRef" :data="tableData" v-loading="loading" stripe border :max-height="maxHeight">
      <el-table-column prop="payment_id" label="回款ID" width="160" show-overflow-tooltip />
      <el-table-column prop="order_id" label="订单ID" width="160" show-overflow-tooltip />
      <el-table-column prop="customer_name" label="客户名称" min-width="140" show-overflow-tooltip />
      <el-table-column label="回款金额" width="110" align="right">
        <template #default="{ row }">{{ row.payment_amount?.toFixed(2) }}</template>
      </el-table-column>
      <el-table-column prop="salesperson_name" label="业务员" width="90" />
      <el-table-column label="业务员比例" width="90" align="right">
        <template #default="{ row }">{{ rateStr(row.salesperson_rate) }}</template>
      </el-table-column>
      <el-table-column label="业务员提成" width="100" align="right">
        <template #default="{ row }">{{ row.salesperson_commission?.toFixed(2) }}</template>
      </el-table-column>
      <el-table-column prop="supervisor_name" label="一级主管" width="90" />
      <el-table-column label="一级主管比例" width="100" align="right">
        <template #default="{ row }">{{ rateStr(row.supervisor_rate) }}</template>
      </el-table-column>
      <el-table-column label="一级主管提成" width="110" align="right">
        <template #default="{ row }">{{ row.supervisor_commission?.toFixed(2) }}</template>
      </el-table-column>
      <el-table-column prop="second_supervisor_name" label="二级主管" width="90" />
      <el-table-column label="二级主管比例" width="100" align="right">
        <template #default="{ row }">{{ rateStr(row.second_supervisor_rate) }}</template>
      </el-table-column>
      <el-table-column label="二级主管提成" width="110" align="right">
        <template #default="{ row }">{{ row.second_supervisor_commission?.toFixed(2) }}</template>
      </el-table-column>
      <el-table-column prop="calc_rule_note" label="计算规则" width="130" />
    </el-table>

    <el-pagination
      class="pagination"
      v-model:current-page="page"
      v-model:page-size="pageSize"
      :total="total"
      layout="total, prev, pager, next, sizes"
      :page-sizes="[20, 50, 100]"
      @current-change="fetchDetails"
      @size-change="fetchDetails"
    />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { getBatchDetails, getBatchSummary } from '@/api/commission'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const { tableRef, maxHeight } = useTableMaxHeight()

const route = useRoute()
const batchId = route.params.batchId

const summary = ref(null)
const keyword = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const tableData = ref([])
const loading = ref(false)

function statusType(s) {
  return { draft: 'info', calculated: '', confirmed: 'success', voided: 'danger' }[s] || 'info'
}
function statusLabel(s) {
  return { draft: '草稿', calculated: '已计算', confirmed: '已确认', voided: '已作废' }[s] || s
}
function rateStr(v) {
  return v != null ? (v * 100).toFixed(1) + '%' : '-'
}

async function fetchSummary() {
  try {
    const res = await getBatchSummary(batchId)
    summary.value = res.data
  } catch { /* ignore */ }
}

async function fetchDetails() {
  loading.value = true
  try {
    const res = await getBatchDetails(batchId, {
      keyword: keyword.value,
      page: page.value,
      page_size: pageSize.value
    })
    tableData.value = res.data.items
    total.value = res.data.total
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchSummary()
  fetchDetails()
})
</script>

<style scoped>
.toolbar { margin-bottom: 16px; }
.pagination { margin-top: 16px; justify-content: flex-end; }

.summary-banner {
  background: linear-gradient(135deg, #141210 0%, #1E1B18 60%, #141210 100%);
  border-radius: 16px;
  padding: 28px 32px;
  margin-bottom: 16px;
  color: #fff;
  position: relative;
  overflow: hidden;
}
.summary-banner::after {
  content: '';
  position: absolute;
  right: -20px;
  top: -20px;
  width: 150px;
  height: 150px;
  border: 2px solid rgba(245,203,92,0.1);
  border-radius: 4px;
  transform: rotate(45deg);
}
.summary-top {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}
.summary-title {
  font-size: 18px;
  font-weight: 700;
}
.summary-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
}
.summary-item {
  background: rgba(255,255,255,0.12);
  border-radius: 8px;
  padding: 12px 16px;
}
.summary-item.highlight {
  background: rgba(255,255,255,0.2);
}
.summary-label {
  font-size: 12px;
  color: rgba(255,255,255,0.7);
  margin-bottom: 4px;
}
.summary-value {
  font-size: 22px;
  font-weight: 700;
}
</style>
