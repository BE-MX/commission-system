<template>
  <div class="commission-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <!-- 批次表格：筛选区 + 操作行 + 表格 + 分页同在卡片内（List Page Spec） -->
    <div ref="panelRef" class="table-card commission-panel commission-lift cm-enter">
      <div class="toolbar">
        <el-radio-group v-model="statusFilter" @change="fetchList">
          <el-radio-button value="">全部</el-radio-button>
          <el-radio-button value="draft">草稿</el-radio-button>
          <el-radio-button value="calculated">已计算</el-radio-button>
          <el-radio-button value="confirming">确认中</el-radio-button>
          <el-radio-button value="confirmed">已确认</el-radio-button>
          <el-radio-button value="voided">已作废</el-radio-button>
        </el-radio-group>
        <GlassButton variant="primary" left-icon="Search" @click="fetchList">查询</GlassButton>
        <GlassButton left-icon="RefreshLeft" @click="resetFilters">重置</GlassButton>
      </div>

      <!-- 操作行：主操作按钮组 + TableTools 四图标（Action Bar Spec） -->
      <div class="action-bar">
        <GlassButton v-permission="'commission:write'" variant="primary" left-icon="Plus" @click="openCreateDialog">新建批次</GlassButton>
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          @refresh="fetchList"
          @fullscreen="toggleFullscreen"
        />
      </div>

      <el-table :data="tableData" v-loading="loading" class="list-table" :class="densityClass" border :max-height="isFullscreen ? undefined : 640" @sort-change="orderSort.onSortChange">
        <template #empty>
          <el-empty :image-size="96" :description="hasActiveFilters ? '没有符合条件的记录' : '暂无数据'">
            <GlassButton v-if="hasActiveFilters" left-icon="RefreshLeft" @click="resetFilters">重置筛选</GlassButton>
          </el-empty>
        </template>
        <el-table-column v-if="visibleKeys.includes('batch-name')" prop="batch_name" label="批次名称" min-width="140" max-width="210" show-overflow-tooltip sortable="custom" />
        <el-table-column v-if="visibleKeys.includes('period-type')" label="周期类型" min-width="90" max-width="140">
          <template #default="{ row }">{{ periodLabel(row.period_type) }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('period-start')" prop="period_start" label="起始日期" min-width="110" max-width="170" show-overflow-tooltip sortable="custom" />
        <el-table-column v-if="visibleKeys.includes('period-end')" prop="period_end" label="结束日期" min-width="110" max-width="170" show-overflow-tooltip sortable="custom" />
        <el-table-column v-if="visibleKeys.includes('status')" prop="status" label="状态" min-width="90" max-width="140" sortable="custom">
          <template #default="{ row }">
            <el-tag :type="batchStatusType(row.status)" size="small" effect="plain">{{ batchStatusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('confirm-progress')" label="确认进度" min-width="160" max-width="220">
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
        <el-table-column v-if="visibleKeys.includes('confirmation-status')" label="确认状态" min-width="110" max-width="160">
          <template #default="{ row }">
            <el-tag :type="confirmationStatusType(row.confirmation_status)" size="small" effect="plain">
              {{ confirmationStatusLabel(row.confirmation_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('feedback-count')" prop="feedback_count" label="反馈数" min-width="80" max-width="120" align="right" />
        <el-table-column v-if="visibleKeys.includes('created-at')" prop="created_at" label="创建时间" min-width="170" max-width="260" show-overflow-tooltip sortable="custom" />
        <el-table-column class-name="table-action-column" label="操作" min-width="280" max-width="420" fixed="right">
          <template #default="{ row }">
            <!-- 草稿 -->
            <template v-if="row.status === 'draft'">
              <GlassButton v-permission="'commission:write'" variant="link" left-icon="DataAnalysis" @click="handleCalculate(row)">执行计算</GlassButton>
            </template>
            <!-- 已计算 -->
            <template v-if="row.status === 'calculated'">
              <GlassButton variant="link" left-icon="View" @click="goDetail(row)">明细</GlassButton>
              <GlassButton v-permission="'commission:write'" variant="link" link-tone="warning" left-icon="Promotion" @click="handleSendConfirm(row)">发送确认</GlassButton>
              <GlassButton v-permission="'commission:write'" variant="link" link-tone="success" left-icon="CircleCheck" @click="handleConfirm(row)">确认</GlassButton>
              <GlassButton v-permission="'commission:write'" variant="link" link-tone="danger" left-icon="CircleClose" @click="handleVoid(row)">作废</GlassButton>
              <CommissionExportMenu :batch-id="row.id" />
            </template>
            <!-- 确认中 -->
            <template v-if="row.status === 'confirming'">
              <GlassButton variant="link" left-icon="View" @click="goDetail(row)">明细</GlassButton>
              <GlassButton v-permission="'commission:write'" variant="link" link-tone="danger" left-icon="RefreshLeft" @click="handleRevokeConfirm(row)">撤销确认</GlassButton>
              <GlassButton v-permission="'commission:write'" variant="link" link-tone="success" left-icon="CircleCheck" @click="handleConfirm(row)">确认</GlassButton>
              <GlassButton v-permission="'commission:write'" variant="link" link-tone="danger" left-icon="CircleClose" @click="handleVoid(row)">作废</GlassButton>
              <CommissionExportMenu :batch-id="row.id" />
            </template>
            <!-- 已确认 -->
            <template v-if="row.status === 'confirmed'">
              <GlassButton variant="link" left-icon="View" @click="goDetail(row)">明细</GlassButton>
              <CommissionExportMenu :batch-id="row.id" />
            </template>
            <!-- 已作废 -->
            <template v-if="row.status === 'voided'">
              <GlassButton variant="link" left-icon="View" @click="goDetail(row)">明细</GlassButton>
            </template>
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
        <el-descriptions-item label="业务员提成合计">{{ usdOrDash(calcResult.total_salesperson_commission) }}</el-descriptions-item>
        <el-descriptions-item label="一级主管提成合计">{{ usdOrDash(calcResult.total_supervisor_commission) }}</el-descriptions-item>
        <el-descriptions-item label="二级主管提成合计">{{ usdOrDash(calcResult.total_second_supervisor_commission) }}</el-descriptions-item>
        <el-descriptions-item label="跳过(归属不完整)">{{ calcResult.skipped_incomplete }}</el-descriptions-item>
        <el-descriptions-item label="跳过(无快照)">{{ calcResult.skipped_no_snapshot }}</el-descriptions-item>
      </el-descriptions>
      <el-alert
        v-if="calcResult && (calcResult.skipped_incomplete > 0 || calcResult.skipped_no_snapshot > 0)"
        type="warning"
        class="calc-result-alert"
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
import { computed, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createBatch, getBatchList, calculateBatch, confirmBatch, voidBatch, sendConfirmBatch, revokeConfirmBatch } from '@/api/commission'
import { useTableSort } from '@/composables/useTableSort'
import { useTableView } from '@/composables/useTableView'
import TableTools from '@/components/TableTools.vue'
import {
  batchStatusLabel,
  batchStatusType,
  confirmPercent,
  confirmationStatusLabel,
  confirmationStatusType,
  periodLabel,
  usdOrDash,
} from './commissionFormat'
import CommissionExportMenu from './components/CommissionExportMenu.vue'

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

const hasActiveFilters = computed(() => Boolean(statusFilter.value))

// 列显隐元数据：TableTools 列设置面板的数据源（模板列保持静态，操作列不进配置）
const columnDefs = [
  { key: 'batch-name', label: '批次名称' },
  { key: 'period-type', label: '周期类型' },
  { key: 'period-start', label: '起始日期' },
  { key: 'period-end', label: '结束日期' },
  { key: 'status', label: '状态' },
  { key: 'confirm-progress', label: '确认进度' },
  { key: 'confirmation-status', label: '确认状态' },
  { key: 'feedback-count', label: '反馈数' },
  { key: 'created-at', label: '创建时间' },
]
// 表格视图状态（列显隐/密度/全屏）走全局基建 useTableView（Action Bar Spec）
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } =
  useTableView('commission-batch', columnDefs)

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

function resetFilters() {
  statusFilter.value = ''
  page.value = 1
  fetchList()
}

function handleSizeChange() {
  page.value = 1
  fetchList()
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

function goDetail(row) {
  router.push(`/commission/batch/${row.id}/details`)
}

onMounted(fetchList)
</script>

<style scoped src="./commission.css"></style>

<style scoped>
.confirm-progress {
  display: grid;
  grid-template-columns: 44px 1fr;
  gap: 8px;
  align-items: center;
}

.calc-result-alert {
  margin-top: 16px;
}

.send-confirm-content {
  margin-bottom: 14px;
  color: var(--text-primary);
  line-height: 1.6;
}
</style>
