<template>
  <div>
    <!-- 状态Tab + 新建 -->
    <el-row class="toolbar" justify="space-between" align="middle">
      <el-col :span="18">
        <el-radio-group v-model="statusFilter" @change="fetchList">
          <el-radio-button value="">全部</el-radio-button>
          <el-radio-button value="draft">草稿</el-radio-button>
          <el-radio-button value="calculated">已计算</el-radio-button>
          <el-radio-button value="confirmed">已确认</el-radio-button>
          <el-radio-button value="voided">已作废</el-radio-button>
        </el-radio-group>
      </el-col>
      <el-col :span="6" style="text-align:right">
        <el-button type="primary" @click="openCreateDialog"><el-icon><Plus /></el-icon> 新建批次</el-button>
      </el-col>
    </el-row>

    <!-- 表格 -->
    <el-table ref="tableRef" :data="tableData" v-loading="loading" stripe border :max-height="maxHeight">
      <el-table-column prop="batch_name" label="批次名称" min-width="140" />
      <el-table-column label="周期类型" width="90">
        <template #default="{ row }">{{ periodLabel(row.period_type) }}</template>
      </el-table-column>
      <el-table-column prop="period_start" label="起始日期" width="110" />
      <el-table-column prop="period_end" label="结束日期" width="110" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="170" />
      <el-table-column label="操作" width="280" fixed="right">
        <template #default="{ row }">
          <!-- 草稿 -->
          <template v-if="row.status === 'draft'">
            <el-button link type="primary" @click="handleCalculate(row)"><el-icon><DataAnalysis /></el-icon> 执行计算</el-button>
          </template>
          <!-- 已计算 -->
          <template v-if="row.status === 'calculated'">
            <el-button link type="primary" @click="goDetail(row)"><el-icon><View /></el-icon> 明细</el-button>
            <el-button link type="success" @click="handleConfirm(row)"><el-icon><CircleCheck /></el-icon> 确认</el-button>
            <el-button link type="danger" @click="handleVoid(row)"><el-icon><CircleClose /></el-icon> 作废</el-button>
            <el-dropdown trigger="click" @command="cmd => handleExport(row, cmd)">
              <el-button link type="primary">
                <el-icon><Download /></el-icon> 导出 <el-icon class="el-icon--right"><ArrowDown /></el-icon>
              </el-button>
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
            <el-button link type="primary" @click="goDetail(row)"><el-icon><View /></el-icon> 明细</el-button>
            <el-dropdown trigger="click" @command="cmd => handleExport(row, cmd)">
              <el-button link type="primary">
                <el-icon><Download /></el-icon> 导出 <el-icon class="el-icon--right"><ArrowDown /></el-icon>
              </el-button>
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
            <el-button link type="primary" @click="goDetail(row)"><el-icon><View /></el-icon> 明细</el-button>
          </template>
        </template>
      </el-table-column>
    </el-table>

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
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitCreate">创建</el-button>
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
        <el-button type="primary" @click="calcResultVisible = false">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createBatch, getBatchList, calculateBatch, confirmBatch, voidBatch } from '@/api/commission'
import { exportCommissionDetails, exportSalespersonSummary, exportSupervisorSummary } from '@/api/report'
import { downloadBlob } from '@/utils/download'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const { tableRef, maxHeight } = useTableMaxHeight()

const router = useRouter()
const statusFilter = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const tableData = ref([])
const loading = ref(false)
const saving = ref(false)

function statusType(s) {
  return { draft: 'info', calculated: '', confirmed: 'success', voided: 'danger' }[s] || 'info'
}
function statusLabel(s) {
  return { draft: '草稿', calculated: '已计算', confirmed: '已确认', voided: '已作废' }[s] || s
}
function periodLabel(p) {
  return { monthly: '月度', quarterly: '季度', semi_annual: '半年', annual: '年度' }[p] || p
}

async function fetchList() {
  loading.value = true
  try {
    const res = await getBatchList({
      status: statusFilter.value, page: page.value, page_size: pageSize.value
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
</style>
