<!--
  历史品名映射（产品风向标 P0）：旧产品库时期的订单品名 → 型号 + 默认克重。
  标记/样式照 system/DictManagement.vue，分页编排照 expo/ExpoLeads.vue（宪法 14）。
  需求：docs/requirements/2026-11-18-product-sales-radar/README.md
-->
<template>
  <div class="mapping-page">
    <section class="coverage-card" aria-label="月度销量可信度">
      <div class="coverage-head">
        <div>
          <h3>月度销量可信度</h3>
          <p>按件数计：确切重量占比 ≥ {{ thresholdText }} 才算可信月，参与趋势结论；其余月份只作估算。确认映射是「采纳克重假设」，不会让估算月变可信。</p>
        </div>
        <GlassButton left-icon="Refresh" :variant="coverageStale ? 'primary' : undefined" :loading="coverageLoading" @click="loadCoverage">{{ coverageStale ? '映射已变更，重新计算' : '重新计算' }}</GlassButton>
      </div>
      <ListPageStatus :error="coverageError" :loading="coverageLoading" :has-data="months.length > 0" @retry="loadCoverage" />
      <ol v-if="months.length" class="coverage-months">
        <li v-for="m in months" :key="m.month" :class="m.credible ? 'is-credible' : 'is-estimate'" :title="monthTitle(m)">
          <span class="coverage-month">{{ m.month.slice(2) }}</span>
          <span class="coverage-share">{{ percent(m.credible_share) }}</span>
        </li>
      </ol>
    </section>

    <div class="table-card">
      <div class="toolbar">
        <el-select v-model="searchForm.status" placeholder="全部状态" clearable class="filter-w-md" @change="guarded(handleSearch)">
          <el-option v-for="opt in STATUS_OPTIONS" :key="opt.value" :label="`${opt.label}（${statusCounts[opt.value] ?? 0}）`" :value="opt.value" />
        </el-select>
        <el-input v-model="searchForm.keyword" placeholder="品名或型号" clearable class="filter-w-lg" @keyup.enter="guarded(handleSearch)" @clear="guarded(handleSearch)" />
        <GlassButton variant="primary" left-icon="Search" @click="guarded(handleSearch)">查询</GlassButton>
        <GlassButton left-icon="RefreshLeft" @click="guarded(handleReset)">重置</GlassButton>
      </div>

      <div class="action-bar">
        <GlassButton v-permission="'product_sales:admin'" variant="primary" left-icon="Check" :disabled="!selectedReady.length" :loading="saving" @click="confirmSelected">
          确认所选（{{ selectedReady.length }}）
        </GlassButton>
        <GlassButton v-permission="'product_sales:admin'" left-icon="MagicStick" :loading="refreshing" @click="guarded(refreshSuggestions)">扫描新品名</GlassButton>
        <span class="action-hint">按涉及件数从多到少排序；选型号会自动带出该型号的常用克重。<template v-if="dirtyCount">有 {{ dirtyCount }} 行修改未保存。</template></span>
      </div>

      <ListPageStatus v-if="hasData" :error="errorMessage" :loading="loading" :has-data="hasData" :data-page="dataPage" @retry="fetchList" />
      <el-table :data="list" v-loading="loading" border class="list-table" row-key="id" :max-height="640" v-sticky-scrollbar @selection-change="rows => (selection = rows)">
        <template #empty><ListPageStatus :error="errorMessage" :loading="loading" :has-data="false" @retry="fetchList">
          <el-empty :image-size="96" description="暂无待处理品名，点「扫描新品名」从订单中生成" />
        </ListPageStatus></template>
        <el-table-column type="selection" min-width="44" :selectable="row => row.status !== 'ignored'" />
        <el-table-column prop="product_name" label="订单品名" min-width="240" show-overflow-tooltip />
        <el-table-column label="涉及件数" min-width="110" align="right">
          <template #default="{ row }">{{ formatNumber(row.quantity_total) }}<span class="cell-sub"> / {{ row.line_count }} 行</span></template>
        </el-table-column>
        <el-table-column prop="last_seen_date" label="最近出现" min-width="110" />
        <el-table-column label="型号" min-width="220">
          <template #default="{ row }">
            <el-select v-model="row.model" filterable allow-create default-first-option clearable placeholder="选择或输入型号" class="cell-input" :disabled="row.status === 'ignored'" @change="value => onModelChange(row, value)">
              <el-option v-for="m in modelOptions" :key="m.model" :label="`${m.model}（${m.unit_grams}g）`" :value="m.model" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="每件克重" min-width="140">
          <template #default="{ row }">
            <el-input-number v-model="row.unit_grams" :min="0.001" :max="5000" :precision="3" :step="1" controls-position="right" class="cell-input" :disabled="row.status === 'ignored'" />
          </template>
        </el-table-column>
        <el-table-column label="来源 / 状态" min-width="150">
          <template #default="{ row }">
            <StatusBadge size="small" effect="plain" :type="STATUS_TYPE[row.status]">{{ STATUS_LABEL[row.status] }}</StatusBadge>
            <span v-if="row.status === 'suggested'" class="cell-sub">{{ SOURCE_LABEL[row.suggestion_source] || '无建议' }}</span>
          </template>
        </el-table-column>
        <el-table-column class-name="table-action-column" label="操作" min-width="200" fixed="right">
          <template #default="{ row }">
            <GlassButton v-permission="'product_sales:admin'" variant="link" left-icon="Check" :disabled="!isReady(row)" @click="saveRows([row], 'confirmed')">确认</GlassButton>
            <GlassButton v-if="row.status !== 'ignored'" v-permission="'product_sales:admin'" variant="link" link-tone="warning" left-icon="Hide" @click="saveRows([row], 'ignored')">非发制品</GlassButton>
            <GlassButton v-else v-permission="'product_sales:admin'" variant="link" left-icon="RefreshLeft" @click="saveRows([row], 'suggested')">恢复</GlassButton>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        :current-page="page" :page-size="pageSize" :total="total"
        :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next"
        class="pager" @current-change="value => guarded(() => handlePageChange(value))" @size-change="value => guarded(() => handleSizeChange(value))"
      />
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'

import { getSalesCoverage, listCurrentModels, listNameMappings, refreshNameMappings, saveNameMappings } from '@/api/productSales'
import { useListPage } from '@/composables/useListPage'
import { errorMessage as toErrorMessage } from '@/utils/errors'
import { confirmAction, msgSuccessText, msgWarning } from '@/utils/feedback'
import { formatMoney } from '@/utils/money'

const STATUS_OPTIONS = [
  { value: 'suggested', label: '待确认' },
  { value: 'confirmed', label: '已确认' },
  { value: 'ignored', label: '非发制品' },
]
const STATUS_LABEL = Object.fromEntries(STATUS_OPTIONS.map(opt => [opt.value, opt.label]))
const STATUS_TYPE = { suggested: 'warning', confirmed: 'success', ignored: 'info' }
const SOURCE_LABEL = { okki_model: '同名型号', category_rule: '产品清单克重', name_grams: '品名含克重' }

const statusCounts = ref({})
const {
  loading, list, total, page, pageSize, searchForm, appliedSearchForm, errorMessage, hasData, dataPage,
  fetchList, handleSearch, handleReset, handlePageChange, handleSizeChange,
} = useListPage(async (params, { signal, isCurrent }) => {
  const query = { page: params.page, page_size: params.page_size }
  if (params.status) query.status = params.status
  if (params.keyword) query.keyword = params.keyword.trim()
  const data = await listNameMappings(query, { signal, suppressToast: true })
  if (isCurrent()) statusCounts.value = data.status_counts || {}
  return data
}, { searchForm: { status: 'suggested', keyword: '' } })

const modelOptions = ref([])
const modelGrams = computed(() => Object.fromEntries(modelOptions.value.map(m => [m.model, m.unit_grams])))
const selection = ref([])
const saving = ref(false)
const refreshing = ref(false)

// 行内编辑的基线：列表重新加载会丢掉未保存的修改，所以离开当前页前要提示。
const baseline = ref(new Map())
const snapshot = row => ({ model: row.model ?? null, unit_grams: row.unit_grams ?? null })
const editKey = row => `${(row.model || '').trim()}|${row.unit_grams ?? ''}`
watch(list, rows => { baseline.value = new Map(rows.map(row => [row.id, snapshot(row)])) })
const dirtyRows = computed(() => list.value.filter(row => editKey(baseline.value.get(row.id) || {}) !== editKey(row)))
const dirtyCount = computed(() => dirtyRows.value.length)

async function confirmDiscard() {
  if (!dirtyCount.value) return true
  try {
    await confirmAction(`有 ${dirtyCount.value} 行修改未保存，继续会丢弃这些修改。`, '未保存的修改', { type: 'warning', confirmButtonText: '丢弃并继续', cancelButtonText: '留在本页' })
    return true
  } catch { return false }
}
async function guarded(action) {
  if (await confirmDiscard()) return action()
  // 留在本页：筛选框回到当前列表实际使用的条件，避免界面与数据不一致
  Object.assign(searchForm, appliedSearchForm.value)
}

const isReady = row => row.status !== 'ignored' && !!(row.model || '').trim() && Number(row.unit_grams) > 0
const selectedReady = computed(() => selection.value.filter(isReady))

function onModelChange(row, value) {
  const grams = modelGrams.value[value]
  if (grams) row.unit_grams = grams
}

async function saveRows(rows, status) {
  saving.value = true
  try {
    await saveNameMappings(rows.map(row => ({
      id: row.id, status, model: (row.model || '').trim() || null, unit_grams: row.unit_grams ?? null,
    })))
    msgSuccessText(status === 'confirmed' ? `已确认 ${rows.length} 条` : '已更新')
    // 只更新保存过的行，不重新拉列表，其他行未保存的修改得以保留；计数与可信度按需刷新。
    rows.forEach((row) => {
      if (row.status !== status) {
        statusCounts.value[row.status] = Math.max(0, (statusCounts.value[row.status] || 1) - 1)
        statusCounts.value[status] = (statusCounts.value[status] || 0) + 1
      }
      if (status === 'ignored') {
        // 后端标「非发制品」不写克重、空型号不覆盖：界面回到已入库的值
        const saved = baseline.value.get(row.id) || {}
        if (!(row.model || '').trim()) row.model = saved.model ?? null
        row.unit_grams = saved.unit_grams ?? null
      }
      row.status = status
      baseline.value.set(row.id, snapshot(row))
    })
    coverageStale.value = true
  } catch { /* handled by interceptor */ } finally {
    saving.value = false
  }
}

function confirmSelected() {
  const skipped = selection.value.length - selectedReady.value.length
  if (skipped) msgWarning(`${skipped} 条缺型号或克重，已跳过`)
  return saveRows(selectedReady.value, 'confirmed')
}

async function refreshSuggestions() {
  refreshing.value = true
  try {
    const result = await refreshNameMappings()
    msgSuccessText(`新增 ${result.created} 个品名，待确认共 ${result.pending} 个`)
    await fetchList({ adjustPage: true })
  } catch { /* handled by interceptor */ } finally {
    refreshing.value = false
  }
}

const months = ref([])
const threshold = ref(0.9)
const coverageLoading = ref(false)
const coverageError = ref('')
const coverageStale = ref(false)
const thresholdText = computed(() => percent(threshold.value))

async function loadCoverage() {
  coverageLoading.value = true
  coverageError.value = ''
  try {
    const data = await getSalesCoverage({}, { suppressToast: true })
    months.value = data.months || []
    threshold.value = data.credible_share_threshold ?? 0.9
    coverageStale.value = false
  } catch (error) {
    coverageError.value = toErrorMessage(error)
  } finally {
    coverageLoading.value = false
  }
}

const percent = value => `${Math.round((Number(value) || 0) * 100)}%`
const formatNumber = value => formatMoney(value, 0)
const monthTitle = m => `${m.month}：${formatNumber(m.quantity)} 件，确切 ${percent(m.credible_share)}，合计 ${formatMoney(m.kg, 1)} kg（含估算）`

onMounted(async () => {
  loadCoverage()
  try {
    modelOptions.value = await listCurrentModels({ suppressToast: true })
  } catch { modelOptions.value = [] }
})
</script>

<style scoped>
.mapping-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.coverage-card {
  padding: 16px 20px;
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
}

.coverage-head {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  justify-content: space-between;
}

.coverage-head h3 {
  margin: 0 0 4px;
  font-size: 15px;
}

.coverage-head p {
  margin: 0;
  color: var(--text-secondary);
  font-size: 13px;
}

.coverage-months {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(64px, 1fr));
  gap: 6px;
  margin: 14px 0 0;
  padding: 0;
  list-style: none;
}

.coverage-months li {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 6px 4px;
  border-radius: 8px;
  font-variant-numeric: tabular-nums;
}

.coverage-months .is-credible {
  background: var(--color-success-bg);
  color: var(--color-success-text);
}

.coverage-months .is-estimate {
  background: repeating-linear-gradient(135deg, var(--color-info-bg) 0 4px, var(--border-color) 4px 5px);
  color: var(--text-secondary);
}

.coverage-month {
  font-size: 12px;
}

.coverage-share {
  font-weight: 600;
  font-size: 13px;
}

.action-hint {
  color: var(--text-secondary);
  font-size: 12px;
}

.cell-sub {
  margin-left: 4px;
  color: var(--text-secondary);
  font-size: 12px;
}

.cell-input {
  width: 100%;
}

@media (max-width: 768px) {
  .coverage-head {
    flex-direction: column;
  }
}
</style>
