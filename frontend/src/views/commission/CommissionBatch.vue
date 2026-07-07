<template>
  <div>
    <!-- 状态Tab + 新建 -->
    <el-row class="toolbar" justify="space-between" align="middle">
      <el-col :span="18">
        <el-radio-group v-model="statusFilter" @change="fetchList">
          <el-radio-button value="">全部</el-radio-button>
          <el-radio-button value="draft">草稿</el-radio-button>
          <el-radio-button value="calculated">已计算</el-radio-button>
          <el-radio-button value="confirming">确认中</el-radio-button>
          <el-radio-button value="confirmed">已确认</el-radio-button>
          <el-radio-button value="voided">已作废</el-radio-button>
        </el-radio-group>
      </el-col>
      <el-col :span="6" style="text-align:right">
        <GlassButton variant="primary" left-icon="Plus" @click="openCreateDialog">新建批次</GlassButton>
      </el-col>
    </el-row>

    <!-- 表格 -->
    <div class="table-card">
    <el-table ref="tableRef" :data="tableData" v-loading="loading" class="list-table" border :max-height="maxHeight" @sort-change="orderSort.onSortChange">
      <el-table-column prop="batch_name" label="批次名称" min-width="140" max-width="210" show-overflow-tooltip sortable="custom" />
      <el-table-column label="周期类型" min-width="90" max-width="140">
        <template #default="{ row }">{{ periodLabel(row.period_type) }}</template>
      </el-table-column>
      <el-table-column prop="period_start" label="起始日期" min-width="110" max-width="170" show-overflow-tooltip sortable="custom" />
      <el-table-column prop="period_end" label="结束日期" min-width="110" max-width="170" show-overflow-tooltip sortable="custom" />
      <el-table-column prop="status" label="状态" min-width="90" max-width="140" sortable="custom">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small" effect="plain">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="确认进度" min-width="160" max-width="220">
        <template #default="{ row }">
          <div class="confirm-progress">
            <span>{{ row.confirmed_count || 0 }}/{{ row.expected_confirm_count || 0 }}</span>
            <el-progress
              :percentage="confirmPercent(row)"
              :show-text="false"
              :stroke-width="6"
              :status="row.confirmation_status === 'all_confirmed' ? 'success' : ''"
            />
          </div>
        </template>
      </el-table-column>
      <el-table-column label="确认状态" min-width="110" max-width="160">
        <template #default="{ row }">
          <el-tag :type="confirmationStatusType(row.confirmation_status)" size="small" effect="plain">
            {{ confirmationStatusLabel(row.confirmation_status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="feedback_count" label="反馈数" min-width="80" max-width="120" align="right" />
      <el-table-column prop="created_at" label="创建时间" min-width="170" max-width="260" show-overflow-tooltip sortable="custom" />
      <el-table-column label="操作" min-width="280" max-width="420" fixed="right">
        <template #default="{ row }">
          <!-- 草稿 -->
          <template v-if="row.status === 'draft'">
            <GlassButton variant="link" left-icon="DataAnalysis" @click="handleCalculate(row)">执行计算</GlassButton>
          </template>
          <!-- 已计算 -->
          <template v-if="row.status === 'calculated'">
            <GlassButton variant="link" left-icon="View" @click="goDetail(row)">明细</GlassButton>
            <GlassButton variant="link" link-tone="warning" left-icon="Promotion" @click="handleSendConfirm(row)">发送确认</GlassButton>
            <GlassButton variant="link" link-tone="success" left-icon="CircleCheck" @click="handleConfirm(row)">确认</GlassButton>
            <GlassButton variant="link" link-tone="danger" left-icon="CircleClose" @click="handleVoid(row)">作废</GlassButton>
            <el-dropdown trigger="click" @command="cmd => handleExport(row, cmd)">
              <GlassButton variant="link" left-icon="Download" right-icon="ArrowDown">
                导出
              </GlassButton>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="all"><el-icon><Document /></el-icon> 全部明细</el-dropdown-item>
                  <el-dropdown-item command="salesperson"><el-icon><User /></el-icon> 按业务员</el-dropdown-item>
                  <el-dropdown-item command="supervisor"><el-icon><UserFilled /></el-icon> 按一级主管</el-dropdown-item>
                  <el-dropdown-item command="customer"><el-icon><OfficeBuilding /></el-icon> 按客户</el-dropdown-item>
                  <el-dropdown-item command="sp_summary" divided><el-icon><TrendCharts /></el-icon> 业务员汇总</el-dropdown-item>
                  <el-dropdown-item command="sv_summary"><el-icon><TrendCharts /></el-icon> 一级主管汇总</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
          <!-- 确认中 -->
          <template v-if="row.status === 'confirming'">
            <GlassButton variant="link" left-icon="View" @click="goDetail(row)">明细</GlassButton>
            <GlassButton variant="link" link-tone="danger" left-icon="RefreshLeft" @click="handleRevokeConfirm(row)">撤销确认</GlassButton>
            <GlassButton variant="link" link-tone="success" left-icon="CircleCheck" @click="handleConfirm(row)">确认</GlassButton>
            <GlassButton variant="link" link-tone="danger" left-icon="CircleClose" @click="handleVoid(row)">作废</GlassButton>
            <el-dropdown trigger="click" @command="cmd => handleExport(row, cmd)">
              <GlassButton variant="link" left-icon="Download" right-icon="ArrowDown">
                导出
              </GlassButton>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="all"><el-icon><Document /></el-icon> 全部明细</el-dropdown-item>
                  <el-dropdown-item command="salesperson"><el-icon><User /></el-icon> 按业务员</el-dropdown-item>
                  <el-dropdown-item command="supervisor"><el-icon><UserFilled /></el-icon> 按一级主管</el-dropdown-item>
                  <el-dropdown-item command="customer"><el-icon><OfficeBuilding /></el-icon> 按客户</el-dropdown-item>
                  <el-dropdown-item command="sp_summary" divided><el-icon><TrendCharts /></el-icon> 业务员汇总</el-dropdown-item>
                  <el-dropdown-item command="sv_summary"><el-icon><TrendCharts /></el-icon> 一级主管汇总</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
          <!-- 已确认 -->
          <template v-if="row.status === 'confirmed'">
            <GlassButton variant="link" left-icon="View" @click="goDetail(row)">明细</GlassButton>
            <el-dropdown trigger="click" @command="cmd => handleExport(row, cmd)">
              <GlassButton variant="link" left-icon="Download" right-icon="ArrowDown">
                导出
              </GlassButton>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="all"><el-icon><Document /></el-icon> 全部明细</el-dropdown-item>
                  <el-dropdown-item command="salesperson"><el-icon><User /></el-icon> 按业务员</el-dropdown-item>
                  <el-dropdown-item command="supervisor"><el-icon><UserFilled /></el-icon> 按一级主管</el-dropdown-item>
                  <el-dropdown-item command="customer"><el-icon><OfficeBuilding /></el-icon> 按客户</el-dropdown-item>
                  <el-dropdown-item command="sp_summary" divided><el-icon><TrendCharts /></el-icon> 业务员汇总</el-dropdown-item>
                  <el-dropdown-item command="sv_summary"><el-icon><TrendCharts /></el-icon> 一级主管汇总</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
          <!-- 已作废 -->
          <template v-if="row.status === 'voided'">
            <GlassButton variant="link" left-icon="View" @click="goDetail(row)">明细</GlassButton>
          </template>
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

    <!-- 新建批次 Dialog -->
    <el-dialog v-model="createDialogVisible" title="新建提成批次" width="460px">
      <el-form :model="createForm" label-width="90px">
        <el-form-item label="批次名称" required>
          <el-input v-model="createForm.batch_name" placeholder="如：2026年Q2" />
        </el-form-item>
        <el-form-item label="周期类型">
          <el-select v-model="createForm.period_type" style="width:100%">
            <el-option label="月度" value="monthly" />
            <el-option label="季度" value="quarterly" />
            <el-option label="半年" value="semi_annual" />
            <el-option label="年度" value="annual" />
          </el-select>
        </el-form-item>
        <el-form-item label="起止日期" required>
          <el-date-picker
            v-model="createDateRange"
            type="daterange"
            range-separator="至"
            start-placeholder="开始"
            end-placeholder="结束"
            value-format="YYYY-MM-DD"
            style="width:100%"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="createDialogVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="saving" @click="submitCreate">创建</GlassButton>
      </template>
    </el-dialog>

    <!-- 计算结果 Dialog -->
    <el-dialog v-model="calcResultVisible" title="计算结果" width="480px">
      <el-descriptions :column="2" border v-if="calcResult">
        <el-descriptions-item label="参与计算回款数">{{ calcResult.total_payments }}</el-descriptions-item>
        <el-descriptions-item label="业务员提成合计">{{ calcResult.total_salesperson_commission?.toFixed(2) }}</el-descriptions-item>
        <el-descriptions-item label="一级主管提成合计">{{ calcResult.total_supervisor_commission?.toFixed(2) }}</el-descriptions-item>
        <el-descriptions-item label="二级主管提成合计">{{ calcResult.total_second_supervisor_commission?.toFixed(2) }}</el-descriptions-item>
        <el-descriptions-item label="跳过(归属不完整)">{{ calcResult.skipped_incomplete }}</el-descriptions-item>
        <el-descriptions-item label="跳过(无快照)">{{ calcResult.skipped_no_snapshot }}</el-descriptions-item>
      </el-descriptions>
      <el-alert
        v-if="calcResult && (calcResult.skipped_incomplete > 0 || calcResult.skipped_no_snapshot > 0)"
        type="warning"
        style="margin-top:16px"
        :closable="false"
        title="部分回款因客户归属不完整而跳过，请补充后重新计算"
      />
      <template #footer>
        <GlassButton variant="primary" @click="calcResultVisible = false">确定</GlassButton>
      </template>
    </el-dialog>

    <el-dialog v-model="sendConfirmVisible" title="发送确认" width="480px">
      <div class="send-confirm-content">本次提成计算将推送给业务员，是否继续？</div>
      <el-checkbox v-model="sendDingtalkNotify">同步发送钉钉通知</el-checkbox>
      <template #footer>
        <GlassButton variant="ghost" @click="sendConfirmVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="sendConfirmLoading" @click="submitSendConfirm">确定</GlassButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createBatch, getBatchList, calculateBatch, confirmBatch, voidBatch, sendConfirmBatch, revokeConfirmBatch } from '@/api/commission'
import { exportCommissionDetails, exportSalespersonSummary, exportSupervisorSummary } from '@/api/report'
import { downloadBlob } from '@/utils/download'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'
import { useTableSort } from '@/composables/useTableSort'

const { tableRef, maxHeight } = useTableMaxHeight()
const orderSort = useTableSort()

const router = useRouter()
const statusFilter = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const tableData = ref([])
const loading = ref(false)
const saving = ref(false)
const sendConfirmVisible = ref(false)
const sendConfirmLoading = ref(false)
const sendDingtalkNotify = ref(true)
const currentSendConfirmRow = ref(null)

function statusType(s) {
  return { draft: 'info', calculated: '', confirming: 'warning', confirmed: 'success', voided: 'danger' }[s] || 'info'
}
function statusLabel(s) {
  return { draft: '草稿', calculated: '已计算', confirming: '确认中', confirmed: '已确认', voided: '已作废' }[s] || s
}
function confirmationStatusType(s) {
  return { not_required: 'info', not_started: 'info', partial_confirmed: 'warning', all_confirmed: 'success' }[s] || 'info'
}
function confirmationStatusLabel(s) {
  return { not_required: '无需确认', not_started: '未开始', partial_confirmed: '部分确认', all_confirmed: '全部确认' }[s] || s
}
function confirmPercent(row) {
  const expected = Number(row.expected_confirm_count || 0)
  if (!expected) return 0
  return Math.min(Math.round((Number(row.confirmed_count || 0) / expected) * 100), 100)
}
function periodLabel(p) {
  return { monthly: '月度', quarterly: '季度', semi_annual: '半年', annual: '年度' }[p] || p
}

async function fetchList() {
  loading.value = true
  try {
    const res = await getBatchList({
      status: statusFilter.value, page: page.value, page_size: pageSize.value,
      ...orderSort.sortParams.value,
    })
    tableData.value = res.data.items
    total.value = res.data.total
  } finally {
    loading.value = false
  }
}

// 新建批次
const createDialogVisible = ref(false)
const createForm = ref({ batch_name: '', period_type: 'quarterly' })
const createDateRange = ref(null)

function openCreateDialog() {
  createForm.value = { batch_name: '', period_type: 'quarterly' }
  createDateRange.value = null
  createDialogVisible.value = true
}

async function submitCreate() {
  if (!createForm.value.batch_name || !createDateRange.value) {
    ElMessage.warning('请填写必填项')
    return
  }
  saving.value = true
  try {
    await createBatch({
      ...createForm.value,
      period_start: createDateRange.value[0],
      period_end: createDateRange.value[1]
    })
    ElMessage.success('批次创建成功')
    createDialogVisible.value = false
    fetchList()
  } finally {
    saving.value = false
  }
}

// 执行计算
const calcResult = ref(null)
const calcResultVisible = ref(false)

async function handleCalculate(row) {
  try {
    await ElMessageBox.confirm(`确认对「${row.batch_name}」执行提成计算？`, '确认计算')
  } catch { return }

  loading.value = true
  try {
    const res = await calculateBatch(row.id)
    calcResult.value = res.data
    calcResultVisible.value = true
    fetchList()
  } finally {
    loading.value = false
  }
}

// 确认批次
async function handleConfirm(row) {
  try {
    await ElMessageBox.confirm('确认后不可撤销，是否继续？', '确认批次', { type: 'warning' })
  } catch { return }

  try {
    await confirmBatch(row.id, { confirmed_by: '管理员' })
    ElMessage.success('批次已确认')
    fetchList()
  } catch { /* handled by interceptor */ }
}

// 作废批次
async function handleVoid(row) {
  try {
    await ElMessageBox.confirm(`确认作废「${row.batch_name}」？作废后回款将被释放。`, '作废批次', { type: 'warning' })
  } catch { return }

  try {
    await voidBatch(row.id)
    ElMessage.success('批次已作废')
    fetchList()
  } catch { /* handled by interceptor */ }
}

// 发送确认
async function handleSendConfirm(row) {
  currentSendConfirmRow.value = row
  sendDingtalkNotify.value = true
  sendConfirmVisible.value = true
}

async function submitSendConfirm() {
  if (!currentSendConfirmRow.value) return
  sendConfirmLoading.value = true
  try {
    const res = await sendConfirmBatch(currentSendConfirmRow.value.id, {
      notify_dingtalk: sendDingtalkNotify.value,
    })
    const count = res.data?.notified_count || 0
    ElMessage.success(sendDingtalkNotify.value ? `已发送确认，通知 ${count} 位业务员` : '已发送确认，未同步钉钉通知')
    sendConfirmVisible.value = false
    await fetchList()
  } catch { /* handled by interceptor */ }
  finally {
    sendConfirmLoading.value = false
  }
}

// 撤销确认
async function handleRevokeConfirm(row) {
  try {
    await ElMessageBox.confirm(`确认撤销「${row.batch_name}」的确认状态？`, '撤销确认', { type: 'warning' })
  } catch { return }

  try {
    await revokeConfirmBatch(row.id)
    ElMessage.success('已撤销确认')
    fetchList()
  } catch { /* handled by interceptor */ }
}

// 导出
async function handleExport(row, cmd) {
  let res
  if (cmd === 'sp_summary') {
    res = await exportSalespersonSummary(row.id)
  } else if (cmd === 'sv_summary') {
    res = await exportSupervisorSummary(row.id)
  } else {
    const groupBy = cmd === 'all' ? '' : cmd
    res = await exportCommissionDetails(row.id, groupBy)
  }
  downloadBlob(res)
}

function goDetail(row) {
  router.push(`/commission/batch/${row.id}/details`)
}

onMounted(fetchList)
</script>

<style scoped>
.toolbar { margin-bottom: 16px; }
.pagination { margin-top: 16px; justify-content: flex-end; }
.confirm-progress {
  display: grid;
  grid-template-columns: 44px 1fr;
  gap: 8px;
  align-items: center;
}
.send-confirm-content {
  margin-bottom: 14px;
  color: #303133;
  line-height: 1.6;
}
</style>
