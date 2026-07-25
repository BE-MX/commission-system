<template>
  <div class="payment-sync-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="payment-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <!-- 同步操作区 -->
    <div class="sync-action-card">
      <div class="sync-action-left">
        <div class="sync-icon">
          <el-icon :size="22"><Refresh /></el-icon>
        </div>
        <div class="sync-info">
          <div class="sync-title">回款数据同步</div>
          <div class="sync-desc">从业务系统拉取回款数据并自动校验客户归属</div>
        </div>
      </div>
      <div class="sync-action-right">
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          value-format="YYYY-MM-DD"
          style="width: 280px"
        />
        <GlassButton v-permission="'payment:write'" variant="primary" :loading="syncing" @click="handleSync" :disabled="!dateRange" left-icon="Refresh">
          开始同步
        </GlassButton>
      </div>
    </div>

    <!-- 同步结果卡片 -->
    <el-card v-if="syncResult" shadow="never" class="sync-result-card" style="margin-bottom:16px">
      <el-row :gutter="20">
        <el-col :span="4">
          <el-statistic title="回款总数" :value="syncResult.total_payments" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="新同步" :value="syncResult.new_synced" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="已同步" :value="syncResult.already_synced" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="客户校验" :value="syncResult.customers_checked" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="自动生成归属" :value="syncResult.snapshots_auto_created" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="待补充" :value="syncResult.snapshots_incomplete" />
        </el-col>
      </el-row>
      <el-alert
        v-if="syncResult.snapshots_incomplete > 0"
        type="warning"
        style="margin-top:16px"
        :closable="false"
      >
        <template #title>
          {{ syncResult.snapshots_incomplete }} 条客户归属缺失，请
          <el-link type="primary" @click="$router.push('/customer/snapshot')">前往客户归属管理</el-link>
          补充后重新计算
        </template>
      </el-alert>
    </el-card>

    <!-- 已同步回款列表 -->
    <el-card shadow="never" class="payment-panel">
      <template #header>
        <el-row :gutter="16" align="middle">
          <el-col :span="6">
            <el-input v-model="listKeyword" placeholder="搜索" clearable @keyup.enter="fetchPayments" @clear="fetchPayments">
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
          </el-col>
          <el-col :span="2">
            <GlassButton left-icon="Search" @click="fetchPayments">查询</GlassButton>
          </el-col>
        </el-row>
      </template>

      <div class="table-card">
      <el-table ref="tableRef" :data="paymentList" v-loading="listLoading" class="list-table" border :max-height="maxHeight" @sort-change="orderSort.onSortChange">
        <el-table-column prop="payment_id" label="回款ID" min-width="180" max-width="270" show-overflow-tooltip />
        <el-table-column prop="order_id" label="订单ID" min-width="180" max-width="270" show-overflow-tooltip />
        <el-table-column prop="customer_name" label="客户名称" min-width="160" max-width="240" show-overflow-tooltip sortable="custom" />
        <el-table-column prop="payment_date" label="回款日期" min-width="110" max-width="170" show-overflow-tooltip sortable="custom" />
        <el-table-column prop="payment_amount" label="回款金额(USD)" min-width="130" max-width="200" sortable="custom">
          <template #default="{ row }">{{ formatAmount(row.payment_amount) }}</template>
        </el-table-column>
        <el-table-column prop="service_fee" label="服务费" min-width="110" max-width="170">
          <template #default="{ row }">{{ formatAmount(row.service_fee) }}</template>
        </el-table-column>
        <el-table-column prop="exchange_rate" label="汇率" min-width="90" max-width="140">
          <template #default="{ row }">{{ formatAmount(row.exchange_rate, 4) }}</template>
        </el-table-column>
        <el-table-column prop="real_amount_rmb" label="回款金额(RMB)" min-width="140" max-width="210">
          <template #default="{ row }">{{ formatAmount(row.real_amount_rmb) }}</template>
        </el-table-column>
        <el-table-column label="是否已计算" min-width="100" max-width="150">
          <template #default="{ row }">
            <el-tag :type="row.is_calculated ? 'success' : 'info'" size="small" effect="plain">
              {{ row.is_calculated ? '是' : '否' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="所属批次" min-width="120" max-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.batch_id || '-' }}</template>
        </el-table-column>
      </el-table>
      </div>

      <el-pagination
        class="pagination"
        v-model:current-page="listPage"
        v-model:page-size="listPageSize"
        :total="listTotal"
        layout="total, prev, pager, next, sizes"
        :page-sizes="[20, 50, 100]"
        @current-change="fetchPayments"
        @size-change="fetchPayments"
      />
    </el-card>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { syncPayments, getSyncedPayments } from '@/api/payment'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'
import { useTableSort } from '@/composables/useTableSort'

const { tableRef, maxHeight } = useTableMaxHeight()
const orderSort = useTableSort()

// 同步操作
const dateRange = ref(null)
const syncing = ref(false)
const syncResult = ref(null)

async function handleSync() {
  if (!dateRange.value) return
  try {
    await ElMessageBox.confirm(
      `确认同步 ${dateRange.value[0]} 至 ${dateRange.value[1]} 的回款数据？`,
      '确认同步'
    )
  } catch { return }

  syncing.value = true
  try {
    const res = await syncPayments({
      date_start: dateRange.value[0],
      date_end: dateRange.value[1]
    })
    syncResult.value = res.data
    ElMessage.success(`同步完成：新增 ${res.data.new_synced} 条`)
    fetchPayments()
  } finally {
    syncing.value = false
  }
}

// 已同步回款列表
const listKeyword = ref('')
const listPage = ref(1)
const listPageSize = ref(20)
const listTotal = ref(0)
const paymentList = ref([])
const listLoading = ref(false)

function formatAmount(value, digits = 2) {
  return value == null ? '-' : Number(value).toFixed(digits)
}

async function fetchPayments() {
  if (!dateRange.value) return
  listLoading.value = true
  try {
    const res = await getSyncedPayments({
      date_start: dateRange.value[0],
      date_end: dateRange.value[1],
      keyword: listKeyword.value,
      page: listPage.value,
      page_size: listPageSize.value,
      ...orderSort.sortParams.value
    })
    paymentList.value = res.data.items
    listTotal.value = res.data.total
  } finally {
    listLoading.value = false
  }
}
</script>

<style scoped>
.payment-sync-page { position: relative; }
/* 极光外溢一圈，盖住 main-content 的 24/28 padding 环（同工作台/发票页） */
.payment-aurora { inset: -24px -28px; }
/* 内容压到极光之上（点名内容块，不用 > :not(.lg-aurora) 通配，避免误伤弹层定位）。
   .sync-action-card 本身是 sticky + z-index: 3，已在极光之上，不列入 */
.payment-sync-page .sync-result-card,
.payment-sync-page .payment-panel { position: relative; z-index: 1; }
.sync-action-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  /* 吸顶操作条：玻璃底用更实的 --dash-glass-bg-strong，滚动时下方内容透出也不干扰阅读 */
  background: var(--dash-glass-bg-strong);
  border-radius: var(--dash-card-radius);
  padding: 20px 24px;
  margin-bottom: 16px;
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
  border: 1px solid var(--dash-glass-border);
  position: sticky;
  top: 0;
  z-index: 3;
}
/* 同步结果卡 / 列表面板：同款渐变玻璃（scoped 覆盖 el-card 白底） */
.sync-result-card,
.payment-panel {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
}
/* 面板内嵌的 .table-card 只是结构容器，去掉全局白底，避免玻璃里再套白卡 */
.payment-panel .table-card {
  background: transparent;
  border: 0;
  border-radius: 0;
  box-shadow: none;
}
/* 表格融进玻璃：行/表头半透明，透出极光；hover 用更实的白（本表无固定列） */
.payment-panel :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}
.sync-action-left {
  display: flex;
  align-items: center;
  gap: 14px;
}
.sync-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: var(--color-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  box-shadow: 0 2px 8px rgba(212,148,28,0.3);
}
.sync-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}
.sync-desc {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 2px;
}
.sync-action-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.pagination { margin-top: 16px; justify-content: flex-end; }
</style>
