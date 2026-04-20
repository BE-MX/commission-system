<template>
  <div>
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
        <el-button type="primary" :loading="syncing" @click="handleSync" :disabled="!dateRange">
          <el-icon><Refresh /></el-icon> 开始同步
        </el-button>
      </div>
    </div>

    <!-- 同步结果卡片 -->
    <el-card v-if="syncResult" shadow="never" style="margin-bottom:16px">
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
    <el-card shadow="never">
      <template #header>
        <el-row :gutter="16" align="middle">
          <el-col :span="6">
            <el-input v-model="listKeyword" placeholder="搜索" clearable @keyup.enter="fetchPayments" @clear="fetchPayments">
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
          </el-col>
          <el-col :span="2">
            <el-button @click="fetchPayments">查询</el-button>
          </el-col>
        </el-row>
      </template>

      <el-table :data="paymentList" v-loading="listLoading" stripe border>
        <el-table-column prop="payment_id" label="回款ID" width="180" show-overflow-tooltip />
        <el-table-column prop="order_id" label="订单ID" width="180" show-overflow-tooltip />
        <el-table-column prop="customer_name" label="客户名称" min-width="160" show-overflow-tooltip />
        <el-table-column prop="payment_date" label="回款日期" width="110" />
        <el-table-column label="回款金额(USD)" width="130" align="right">
          <template #default="{ row }">{{ row.payment_amount?.toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="是否已计算" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="row.is_calculated ? 'success' : 'info'" size="small">
              {{ row.is_calculated ? '是' : '否' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="所属批次" width="120">
          <template #default="{ row }">{{ row.batch_id || '-' }}</template>
        </el-table-column>
      </el-table>

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

async function fetchPayments() {
  if (!dateRange.value) return
  listLoading.value = true
  try {
    const res = await getSyncedPayments({
      date_start: dateRange.value[0],
      date_end: dateRange.value[1],
      keyword: listKeyword.value,
      page: listPage.value,
      page_size: listPageSize.value
    })
    paymentList.value = res.data.items
    listTotal.value = res.data.total
  } finally {
    listLoading.value = false
  }
}
</script>

<style scoped>
.sync-action-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-radius: var(--card-radius);
  padding: 20px 24px;
  margin-bottom: 16px;
  box-shadow: var(--card-shadow);
  border: 1px solid #ebeef5;
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
  color: #1a1f36;
}
.sync-desc {
  font-size: 12px;
  color: #8c92a4;
  margin-top: 2px;
}
.sync-action-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.pagination { margin-top: 16px; justify-content: flex-end; }
</style>
