<template>
  <div class="accessory-price-config">
    <div class="accessory-heading">
      <div>
        <h3>Hair ExtensionsTools Fee</h3>
        <p>配件价格必须绑定真实的 OKKI 产品和 SKU，发票会按该身份逐行推送。</p>
      </div>
      <el-button v-permission="'invoice_price:write'" type="primary" @click="openDialog()">
        <el-icon><Plus /></el-icon>
        新增配件价格
      </el-button>
    </div>

    <div class="accessory-toolbar">
      <el-input
        v-model="keyword"
        clearable
        placeholder="搜索 Name / Model / Color"
        @keyup.enter="loadRows"
        @clear="loadRows"
      />
      <el-button @click="loadRows">
        <el-icon><Search /></el-icon>
        筛选
      </el-button>
    </div>

    <div class="table-card accessory-table-card">
      <el-table v-loading="loading" :data="rows" class="list-table" border>
        <el-table-column prop="accessory_name" label="Name" min-width="180" show-overflow-tooltip />
        <el-table-column prop="accessory_model" label="Model" min-width="150" show-overflow-tooltip />
        <el-table-column prop="accessory_color" label="Color" min-width="150" show-overflow-tooltip />
        <el-table-column label="标准价" min-width="130">
          <template #default="{ row }">
            {{ row.currency }} {{ formatPrice(row.standard_price) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="160">
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
      width="560px"
      destroy-on-close
    >
      <el-form :model="dialog.form" label-width="92px">
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
            :min="0"
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
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Delete, Edit, Plus, Search } from '@element-plus/icons-vue'
import { confirmDanger, msgSuccess } from '@/utils/feedback'
import {
  deleteAccessoryPrice,
  listAccessoryPrices,
  saveAccessoryPrice,
  searchAccessoryCandidates,
} from '@/api/invoice'

const loading = ref(false)
const saving = ref(false)
const keyword = ref('')
const rows = ref([])
const candidateLoading = ref(false)
const candidates = ref([])
const dialog = reactive({ visible: false, candidate: null, form: emptyForm() })

onMounted(loadRows)

function emptyForm() {
  return {
    id: null,
    product_id: null,
    sku_id: null,
    accessory_name: '',
    accessory_model: '',
    accessory_color: '',
    price: null,
    currency: 'USD',
  }
}

function candidateFromRow(row) {
  return {
    product_id: row.product_id,
    sku_id: row.sku_id,
    accessory_name: row.accessory_name,
    accessory_model: row.accessory_model,
    accessory_color: row.accessory_color,
  }
}

function candidateLabel(row) {
  return `${row.accessory_name} / ${row.accessory_model} / ${row.accessory_color} · SKU ${row.sku_id}`
}

function formatPrice(value) {
  return Number(value || 0).toFixed(2)
}

async function loadRows() {
  loading.value = true
  try {
    const result = await listAccessoryPrices(keyword.value.trim() ? { keyword: keyword.value.trim() } : {})
    rows.value = result.items || []
  } catch {
    rows.value = []
  } finally {
    loading.value = false
  }
}

async function searchCandidates(query) {
  candidateLoading.value = true
  try {
    const result = await searchAccessoryCandidates(query?.trim() ? { keyword: query.trim() } : {})
    candidates.value = result.items || []
  } catch {
    candidates.value = []
  } finally {
    candidateLoading.value = false
  }
}

function selectCandidate(candidate) {
  if (!candidate) return
  Object.assign(dialog.form, candidateFromRow(candidate))
}

function openDialog(row) {
  const candidate = row ? candidateFromRow(row) : null
  dialog.form = row
    ? { ...emptyForm(), ...candidate, id: row.id, price: Number(row.standard_price), currency: row.currency || 'USD' }
    : emptyForm()
  dialog.candidate = candidate
  candidates.value = candidate ? [candidate] : []
  dialog.visible = true
}

function setCurrency(value) {
  dialog.form.currency = String(value || '').toUpperCase().replace(/[^A-Z]/g, '').slice(0, 3)
}

async function saveRow() {
  const form = dialog.form
  if (!dialog.candidate || !form.product_id || !form.sku_id) {
    ElMessage.warning('请搜索并选择真实的 OKKI 产品/SKU')
    return
  }
  if (form.price == null || Number(form.price) < 0) {
    ElMessage.warning('请输入有效的标准价')
    return
  }
  if (!/^[A-Z]{3}$/.test(form.currency)) {
    ElMessage.warning('请输入 3 位大写币种代码，如 USD')
    return
  }
  saving.value = true
  try {
    await saveAccessoryPrice({ ...form, price: Number(form.price).toFixed(2) })
    dialog.visible = false
    msgSuccess('保存')
    await loadRows()
  } finally {
    saving.value = false
  }
}

async function removeRow(row) {
  await confirmDanger('删除', `${row.accessory_name} · SKU ${row.sku_id} 的标准价`)
  await deleteAccessoryPrice(row.id)
  msgSuccess('删除')
  await loadRows()
}
</script>

<style scoped>
.accessory-price-config {
  max-width: 1120px;
}

.accessory-heading,
.accessory-toolbar {
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

.accessory-toolbar {
  margin-bottom: 12px;
}

.accessory-toolbar .el-input {
  width: min(320px, 100%);
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
