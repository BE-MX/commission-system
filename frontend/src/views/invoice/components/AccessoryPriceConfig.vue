<template>
  <div class="accessory-price-config">
    <div class="accessory-heading">
      <div>
        <h3>Hair ExtensionsTools Fee</h3>
        <p>配件价格必须绑定真实的 OKKI 产品和 SKU，发票会按该身份逐行推送。</p>
      </div>
    </div>

    <div ref="panelRef" class="table-card accessory-table-card">
    <FilterBar :loading="loading" :pending="pending" @search="searchRows" @reset="resetFilter">
      <el-input v-model="keyword" clearable class="filter-w-md" placeholder="搜索 Name / Model / Color" />
    </FilterBar>
    <div class="action-bar">
      <GlassButton v-permission="'invoice_price:write'" variant="primary" left-icon="Plus" @click="openDialog()">新增配件价格</GlassButton>
      <TableTools v-model:visible-keys="visibleKeys" v-model:density="density" :columns="columnDefs" :fullscreen="isFullscreen" :loading="loading" @refresh="loadRows" @fullscreen="toggleFullscreen" />
    </div>
      <ListPageStatus v-if="listError && rows.length" :error="listErrorMessage" :loading="loading" :has-data="hasLoaded" :paged="false" @retry="loadRows" />
      <el-table v-loading="loading" :data="rows" class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" border v-sticky-scrollbar>
        <template #empty><ListPageStatus :error="listErrorMessage" :loading="loading" :paged="false" @retry="loadRows"><el-empty description="暂无配件价格" /></ListPageStatus></template>
        <el-table-column v-if="visibleKeys.includes('name')" prop="accessory_name" label="Name" min-width="180" max-width="320" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('model')" prop="accessory_model" label="Model" min-width="150" max-width="240" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('color')" prop="accessory_color" label="Color" min-width="150" max-width="240" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('price')" label="标准价" min-width="110" max-width="150">
          <template #default="{ row }">
            {{ formatMoney(row.standard_price) }}
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('currency')" prop="currency" label="币种" min-width="90" max-width="110" />
        <el-table-column v-if="visibleKeys.includes('updated')" label="更新时间" min-width="170" max-width="240" show-overflow-tooltip>
          <template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column class-name="table-action-column" label="操作" min-width="150" max-width="190" fixed="right">
          <template #default="{ row }">
            <el-button v-permission="'invoice_price:write'" link type="primary" @click="openDialog(row)">
              <el-icon><Edit /></el-icon>
              编辑
            </el-button>
            <el-button v-permission="'invoice_price:write'" link type="danger" @click="removeRow(row)">
              <el-icon><Delete /></el-icon>
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog
      v-model="dialog.visible"
      :title="dialog.form.id ? '编辑配件标准价' : '新增配件标准价'"
      width="640px"
      destroy-on-close
      @close="invalidateCandidateSearch"
    >
      <el-form label-position="top" :model="dialog.form">
        <ListPageStatus v-if="candidateError" :error="candidateErrorMessage" :loading="candidateLoading" :paged="false" @retry="searchCandidates(candidateQuery)" />
        <el-form-item label="OKKI SKU" required>
          <el-select
            v-model="dialog.candidate"
            value-key="sku_id"
            filterable
            remote
            reserve-keyword
            :remote-method="searchCandidates"
            :loading="candidateLoading"
            :no-match-text="'未找到有效 SKU，请先检查 OKKI 产品同步'"
            no-data-text="未找到有效 SKU，请先检查 OKKI 产品同步"
            placeholder="输入 Name / Model / Color 搜索"
            @change="selectCandidate"
          >
            <el-option
              v-for="candidate in candidates"
              :key="`${candidate.product_id}-${candidate.sku_id}`"
              :label="candidateLabel(candidate)"
              :value="candidate"
            />
          </el-select>
          <div class="field-help">仅可选择已同步且未停用的 OKKI 产品/SKU。</div>
        </el-form-item>
        <el-form-item label="Name">
          <el-input :model-value="dialog.form.accessory_name" readonly />
        </el-form-item>
        <el-form-item label="Model">
          <el-input :model-value="dialog.form.accessory_model" readonly />
        </el-form-item>
        <el-form-item label="Color">
          <el-input :model-value="dialog.form.accessory_color" readonly />
        </el-form-item>
        <el-form-item label="标准价" required>
          <el-input-number
            v-model="dialog.form.price"
            :min="0.01"
            :max="99999999.99"
            :precision="2"
            :step="0.01"
            controls-position="right"
          />
        </el-form-item>
        <el-form-item label="币种" required>
          <el-input
            :model-value="dialog.form.currency"
            maxlength="3"
            placeholder="USD"
            @input="setCurrency"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveRow">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { formatMoney } from '../../../utils/money.js'
import { msgWarning, msgError, confirmDanger, msgSuccess } from '@/utils/feedback'
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'

import { Delete, Edit, Plus, Search } from '@element-plus/icons-vue'
import FilterBar from '@/components/FilterBar.vue'
import ListPageStatus from '@/components/ListPageStatus.vue'
import { errorMessage } from '@/utils/errors'
import TableTools from '@/components/TableTools.vue'
import { useTableView } from '@/composables/useTableView'
import { isAmount } from '@/utils/validators'
import {
  buildAccessoryEditorState,
  createLatestAccessorySearch,
  deleteAccessoryPriceRow,
  emptyAccessoryPriceForm,
  saveAccessoryPriceForm,
  shouldShowAccessoryLocalError,
} from '../composables/accessoryPriceConfigState'
import {
  deleteAccessoryPrice,
  listAccessoryPrices,
  saveAccessoryPrice,
  searchAccessoryCandidates,
} from '@/api/invoice'

const loading = ref(false)
const saving = ref(false)
const keyword = ref(''), appliedKeyword = ref(''), listError = ref(null), hasLoaded = ref(false)
const listErrorMessage = computed(() => listError.value ? errorMessage(listError.value) : '')
const pending = computed(() => keyword.value !== appliedKeyword.value)
const rows = ref([])
const columnDefs = [
  { key: 'name', label: 'Name' }, { key: 'model', label: 'Model' },
  { key: 'color', label: 'Color' }, { key: 'price', label: '标准价' },
  { key: 'currency', label: '币种' }, { key: 'updated', label: '更新时间' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } =
  useTableView('invoice-accessory-prices', columnDefs)
const candidateLoading = ref(false)
const candidates = ref([]), candidateError = ref(null)
const candidateErrorMessage = computed(() => candidateError.value ? errorMessage(candidateError.value) : '')
const candidateQuery = ref('')
const dialog = reactive({ visible: false, candidate: null, form: emptyAccessoryPriceForm() })
const runCandidateSearch = createLatestAccessorySearch({
  request: searchAccessoryCandidates,
  applyItems: items => { candidates.value = items },
  applyLoading: value => { candidateLoading.value = value },
  applyError: error => { candidateError.value = error },
})
const runPriceList = createLatestAccessorySearch({
  request: listAccessoryPrices,
  applyItems: items => { rows.value = items; hasLoaded.value = true },
  applyLoading: value => { loading.value = value },
  applyError: error => { listError.value = error },
  clearOnError: false,
})

onMounted(loadRows)
onUnmounted(() => { runPriceList.invalidate(); runCandidateSearch.invalidate() })

function candidateLabel(row) {
  return `${row.accessory_name} / ${row.accessory_model} / ${row.accessory_color} · SKU ${row.sku_id}`
}

function formatDateTime(value) {
  if (!value) return '—'
  return String(value).replace('T', ' ').slice(0, 16)
}

async function loadRows() {
  try {
    await runPriceList(appliedKeyword.value.trim() ? { keyword: appliedKeyword.value.trim() } : {})
    return true
  } catch {
    // The current read error is rendered inline; successful rows are retained.
    return false
  }
}

function searchRows() { appliedKeyword.value = keyword.value; return loadRows() }
function resetFilter() { keyword.value = ''; return searchRows() }

async function searchCandidates(query) {
  candidateQuery.value = query || ''
  try {
    await runCandidateSearch(query?.trim() ? { keyword: query.trim() } : {})
  } catch {
    // The candidate query has its own latest error and retry control.
  }
}

function selectCandidate(candidate) {
  if (!candidate) return
  Object.assign(dialog.form, candidate)
}

function openDialog(row) {
  invalidateCandidateSearch()
  const editor = buildAccessoryEditorState(row)
  dialog.form = editor.form
  dialog.candidate = editor.candidate
  candidates.value = editor.candidate ? [editor.candidate] : []
  dialog.visible = true
}

function invalidateCandidateSearch() {
  runCandidateSearch.invalidate()
}

function setCurrency(value) {
  dialog.form.currency = String(value || '').toUpperCase().replace(/[^A-Z]/g, '').slice(0, 3)
}

async function saveRow() {
  const form = dialog.form
  if (!dialog.candidate || !form.product_id || !form.sku_id) {
    msgWarning('请搜索并选择真实的 OKKI 产品/SKU')
    return
  }
  if (!isAmount(form.price, { format: 'number' })) {
    msgWarning('请输入有效的标准价')
    return
  }
  if (!/^[A-Z]{3}$/.test(form.currency)) {
    msgWarning('请输入 3 位大写币种代码，如 USD')
    return
  }
  saving.value = true
  try {
    await saveAccessoryPriceForm({
      form,
      save: saveAccessoryPrice,
      onSuccess: async () => {
        dialog.visible = false
        msgSuccess('保存')
        await loadRows()
      },
    })
  } catch (error) {
    if (shouldShowAccessoryLocalError(error)) msgError(`保存失败：${error?.message || error}`, error)
  } finally {
    saving.value = false
  }
}

async function removeRow(row) {
  try {
    await deleteAccessoryPriceRow({
      row,
      confirm: () => confirmDanger('删除', `${row.accessory_name} · SKU ${row.sku_id} 的标准价`),
      remove: deleteAccessoryPrice,
      onSuccess: async () => {
        msgSuccess('删除')
        await loadRows()
      },
    })
  } catch (error) {
    if (shouldShowAccessoryLocalError(error)) msgError(`删除失败：${error?.message || error}`, error)
  }
}
</script>

<style scoped>
.accessory-price-config {
  max-width: 1120px;
}

.accessory-heading {
  display: flex;
  align-items: center;
  gap: 12px;
}

.accessory-heading {
  justify-content: space-between;
  margin-bottom: 16px;
}

.accessory-heading h3 {
  margin: 0 0 4px;
  font-family: var(--font-display);
  font-size: 15px;
}

.accessory-heading p,
.field-help {
  color: var(--text-muted);
  font-size: 12px;
}

.accessory-heading p {
  margin: 0;
}

.accessory-table-card {
  padding: 0;
  overflow: hidden;
}

.field-help {
  margin-top: 4px;
  line-height: 1.5;
}

:deep(.el-dialog .el-select),
:deep(.el-dialog .el-input-number) {
  width: 100%;
}
</style>
