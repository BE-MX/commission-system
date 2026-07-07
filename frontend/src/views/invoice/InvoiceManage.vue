<template>
  <div class="invoice-page">
    <div class="page-header">
      <div>
        <h2>订单发票管理</h2>
        <p>客户发票、产品明细、导出与小满同步校验集中处理。</p>
      </div>
      <el-button type="primary" class="primary-action" @click="openCreate">
        <el-icon><Plus /></el-icon>
        新建发票
      </el-button>
    </div>

    <div class="summary-grid">
      <div class="summary-card">
        <span>发票数</span>
        <strong>{{ summary.total }}</strong>
      </div>
      <div class="summary-card">
        <span>可同步</span>
        <strong>{{ summary.ready }}</strong>
      </div>
      <div class="summary-card">
        <span>草稿</span>
        <strong>{{ summary.draft }}</strong>
      </div>
      <div class="summary-card emphasis">
        <span>当前页金额</span>
        <strong>USD {{ money(summary.amount) }}</strong>
      </div>
    </div>

    <section class="table-card invoice-panel">
      <div class="toolbar">
        <el-input
          v-model="filters.keyword"
          clearable
          placeholder="搜索发票号/客户"
          style="width: 260px"
          @keyup.enter="loadInvoices"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-select v-model="filters.status" clearable placeholder="状态" style="width: 150px">
          <el-option label="草稿" value="draft" />
          <el-option label="可同步" value="ready" />
          <el-option label="已同步" value="synced" />
          <el-option label="同步失败" value="sync_failed" />
        </el-select>
        <el-button @click="loadInvoices">
          <el-icon><Search /></el-icon>
          筛选
        </el-button>
      </div>

      <el-table v-loading="loading" :data="invoices" border class="list-table invoice-table">
        <template #empty>
          <div class="empty-state">
            <strong>暂无发票</strong>
            <span>新建一张发票后会显示在这里。</span>
          </div>
        </template>
        <el-table-column prop="invoice_no" label="发票号" min-width="150" max-width="220" show-overflow-tooltip />
        <el-table-column prop="customer_name" label="客户" min-width="220" max-width="360" show-overflow-tooltip />
        <el-table-column prop="invoice_date" label="日期" min-width="120" max-width="150" show-overflow-tooltip />
        <el-table-column prop="item_count" label="明细" min-width="80" max-width="110" align="right" />
        <el-table-column label="金额" min-width="140" max-width="190" align="right">
          <template #default="{ row }">{{ row.currency }} {{ money(row.total_amount) }}</template>
        </el-table-column>
        <el-table-column label="状态" min-width="110" max-width="150">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" effect="plain">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="同步" min-width="120" max-width="160">
          <template #default="{ row }">
            <el-tag :type="syncType(row.sync_status)" effect="plain">{{ syncText(row.sync_status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" prop="created_at" min-width="170" max-width="240" show-overflow-tooltip />
        <el-table-column label="操作" min-width="330" max-width="390" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button link type="primary" @click="openEdit(row.id)">
                <el-icon><Edit /></el-icon>
                编辑
              </el-button>
              <el-button link @click="exportExcel(row.id)">
                <el-icon><Download /></el-icon>
                Excel
              </el-button>
              <el-button link @click="exportPdf(row.id)">
                <el-icon><Download /></el-icon>
                PDF
              </el-button>
              <el-button link @click="openPrint(row.id)">
                <el-icon><Printer /></el-icon>
                打印
              </el-button>
              <el-button link type="warning" @click="validateAndSync(row.id)">
                <el-icon><Refresh /></el-icon>
                同步
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <div class="pagination-bar">
      <el-pagination
        v-model:current-page="pagination.page"
        v-model:page-size="pagination.page_size"
        :total="pagination.total"
        :page-sizes="[20, 50, 100]"
        layout="total,sizes,prev,pager,next,jumper"
        @size-change="loadInvoices"
        @current-change="loadInvoices"
      />
    </div>

    <el-drawer v-model="drawerVisible" :title="form.id ? `编辑发票 ${form.invoice_no}` : '新建发票'" size="92%">
      <template #default>
        <el-form ref="formRef" :model="form" label-width="110px" class="invoice-form">
          <div class="form-grid">
            <el-form-item label="客户" required>
              <el-select
                v-model="selectedCustomer"
                value-key="company_id"
                filterable
                remote
                reserve-keyword
                :remote-method="searchCustomers"
                :loading="customerLoading"
                placeholder="输入客户名称/ID 搜索"
                style="width: 100%"
                @change="onCustomerChange"
              >
                <el-option
                  v-for="customer in customerOptions"
                  :key="customer.company_id"
                  :label="`${customer.company_name} (${customer.company_id})`"
                  :value="customer"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="日期" required>
              <el-date-picker v-model="form.invoice_date" value-format="YYYY-MM-DD" style="width: 100%" />
            </el-form-item>
            <el-form-item label="币种">
              <el-input v-model="form.currency" maxlength="16" />
            </el-form-item>
            <el-form-item label="备注" class="wide">
              <el-input v-model="form.remark" type="textarea" :rows="2" maxlength="500" />
            </el-form-item>
          </div>

          <div class="line-header">
            <div>
              <strong>产品明细</strong>
              <span>四个关键词选择完整后自动匹配唯一 Product_name。</span>
            </div>
            <el-button @click="addLine">
              <el-icon><Plus /></el-icon>
              添加明细
            </el-button>
          </div>

          <div class="line-table-wrap">
            <el-table :data="form.items" border class="list-table line-table">
              <el-table-column label="#" type="index" min-width="48" max-width="60" fixed />
              <el-table-column label="Model" min-width="150" max-width="220">
                <template #default="{ row }">
                  <el-select v-model="row.model" filterable placeholder="Model" @visible-change="v => v && loadLineOptions(row)" @change="onLineFilterChange(row)">
                    <el-option v-for="v in row.options.models" :key="v" :label="v" :value="v" />
                  </el-select>
                </template>
              </el-table-column>
              <el-table-column label="Color" min-width="150" max-width="220">
                <template #default="{ row }">
                  <el-select v-model="row.color" filterable placeholder="Color" @visible-change="v => v && loadLineOptions(row)" @change="onLineFilterChange(row)">
                    <el-option v-for="v in row.options.colors" :key="v" :label="v" :value="v" />
                  </el-select>
                </template>
              </el-table-column>
              <el-table-column label="Length" min-width="140" max-width="190">
                <template #default="{ row }">
                  <el-select v-model="row.length" filterable placeholder="Length" @visible-change="v => v && loadLineOptions(row)" @change="onLineFilterChange(row)">
                    <el-option v-for="v in row.options.sizes" :key="v" :label="v" :value="v" />
                  </el-select>
                </template>
              </el-table-column>
              <el-table-column label="Net Weight Grams" min-width="170" max-width="230">
                <template #default="{ row }">
                  <el-select v-model="row.net_weight_grams" filterable placeholder="Unit" @visible-change="v => v && loadLineOptions(row)" @change="onLineFilterChange(row)">
                    <el-option v-for="v in row.options.units" :key="v" :label="v" :value="v" />
                  </el-select>
                </template>
              </el-table-column>
              <el-table-column label="Product_name" min-width="280" max-width="420" show-overflow-tooltip>
                <template #default="{ row }">
                  <div :class="['product-cell', row.product_name ? 'is-matched' : 'is-pending']">
                    <span>{{ row.product_name || '待匹配' }}</span>
                    <el-tag v-if="row.sku_id" size="small" effect="plain">SKU {{ row.sku_id }}</el-tag>
                    <el-tag v-else-if="row.matching" size="small" type="info" effect="plain">匹配中</el-tag>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="Product" min-width="160" max-width="240" show-overflow-tooltip>
                <template #default="{ row }">{{ row.product_display || '-' }}</template>
              </el-table-column>
              <el-table-column label="Curl" min-width="130" max-width="180">
                <template #default="{ row }">
                  <el-select v-model="row.curl" clearable placeholder="可选">
                    <el-option v-for="v in curlOptions" :key="v" :label="v" :value="v" />
                  </el-select>
                </template>
              </el-table-column>
              <el-table-column label="Quantity" min-width="120" max-width="160">
                <template #default="{ row }">
                  <el-input-number v-model="row.quantity" :min="1" :precision="0" controls-position="right" @change="updateLineTotal(row)" />
                </template>
              </el-table-column>
              <el-table-column label="Price/Piece" min-width="130" max-width="180">
                <template #default="{ row }">
                  <el-input-number v-model="row.price_per_piece" :min="0.01" :precision="4" controls-position="right" @change="updateLineTotal(row)" />
                </template>
              </el-table-column>
              <el-table-column label="TotalPrice" min-width="130" max-width="180" align="right">
                <template #default="{ row }">{{ money(row.total_price) }}</template>
              </el-table-column>
              <el-table-column label="操作" min-width="80" max-width="100" fixed="right">
                <template #default="{ $index }">
                  <el-button link type="danger" @click="removeLine($index)">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-form>
      </template>

      <template #footer>
        <div class="drawer-footer">
          <div class="total-box">
            Total: <strong>{{ form.currency }} {{ money(formTotal) }}</strong>
          </div>
          <div>
            <el-button @click="drawerVisible = false">取消</el-button>
            <el-button @click="saveDraft">保存</el-button>
            <el-button type="primary" @click="saveAndValidate">保存并校验</el-button>
          </div>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Download, Edit, Plus, Printer, Refresh, Search } from '@element-plus/icons-vue'
import {
  createInvoice,
  downloadInvoiceExcel,
  downloadInvoicePdf,
  getInvoice,
  getInvoicePrintUrl,
  getInvoiceProductOptions,
  listInvoices,
  matchInvoiceProduct,
  searchInvoiceCustomers,
  syncInvoice,
  updateInvoice,
  validateInvoice,
} from '@/api/invoice'

const loading = ref(false)
const drawerVisible = ref(false)
const customerLoading = ref(false)
const invoices = ref([])
const customerOptions = ref([])
const selectedCustomer = ref(null)
const curlOptions = ['Straight', 'Body Wave', 'Deep Wave', 'Loose Wave', 'Kinky Curly', 'Water Wave']

const filters = reactive({ keyword: '', status: '' })
const pagination = reactive({ page: 1, page_size: 20, total: 0 })

const form = reactive(emptyForm())

const formTotal = computed(() => form.items.reduce((sum, line) => sum + Number(line.total_price || 0), 0))
const summary = computed(() => {
  return invoices.value.reduce((acc, invoice) => {
    acc.total += 1
    acc.amount += Number(invoice.total_amount || 0)
    if (invoice.status === 'ready') acc.ready += 1
    if (invoice.status === 'draft') acc.draft += 1
    return acc
  }, { total: 0, ready: 0, draft: 0, amount: 0 })
})

onMounted(() => {
  loadInvoices()
})

function emptyForm() {
  return {
    id: null,
    invoice_no: '',
    customer_id: '',
    customer_name: '',
    invoice_date: new Date().toISOString().slice(0, 10),
    currency: 'USD',
    remark: '',
    items: [],
  }
}

function resetForm(data = emptyForm()) {
  Object.assign(form, {
    ...data,
    items: (data.items || []).map(normalizeLine),
  })
  selectedCustomer.value = form.customer_id
    ? { company_id: form.customer_id, company_name: form.customer_name }
    : null
}

async function loadInvoices() {
  loading.value = true
  try {
    const res = await listInvoices({ ...filters, page: pagination.page, page_size: pagination.page_size })
    invoices.value = res.items || []
    pagination.total = res.total || 0
  } finally {
    loading.value = false
  }
}

async function searchCustomers(keyword) {
  customerLoading.value = true
  try {
    const res = await searchInvoiceCustomers({ keyword })
    customerOptions.value = res.items || []
  } finally {
    customerLoading.value = false
  }
}

function onCustomerChange(customer) {
  form.customer_id = customer?.company_id == null ? '' : String(customer.company_id)
  form.customer_name = customer?.company_name || ''
}

function openCreate() {
  resetForm()
  addLine()
  drawerVisible.value = true
  searchCustomers('')
}

async function openEdit(id) {
  const data = await getInvoice(id)
  resetForm(data)
  drawerVisible.value = true
}

function addLine() {
  form.items.push(normalizeLine({ quantity: 1 }))
}

function removeLine(index) {
  form.items.splice(index, 1)
}

function normalizeLine(line = {}) {
  return {
    product_id: line.product_id || null,
    sku_id: line.sku_id || null,
    product_name: line.product_name || '',
    product_display: line.product_display || '',
    net_weight_grams: line.net_weight_grams || '',
    curl: line.curl || '',
    model: line.model || '',
    color: line.color || '',
    length: line.length || '',
    quantity: Number(line.quantity || 1),
    price_per_piece: line.price_per_piece == null ? null : Number(line.price_per_piece),
    total_price: Number(line.total_price || 0),
    price_source: line.price_source || 'manual',
    options: { models: [], colors: [], sizes: [], units: [] },
    matching: false,
  }
}

async function loadLineOptions(row) {
  const res = await getInvoiceProductOptions({
    model: row.model || undefined,
    color: row.color || undefined,
    size: row.length || undefined,
    unit: row.net_weight_grams || undefined,
  })
  row.options = {
    models: res.models || [],
    colors: res.colors || [],
    sizes: res.sizes || [],
    units: res.units || [],
  }
}

async function onLineFilterChange(row) {
  row.product_id = null
  row.sku_id = null
  row.product_name = ''
  row.product_display = ''
  await loadLineOptions(row)
  if (row.model && row.color && row.length && row.net_weight_grams) {
    await matchLineProduct(row)
  }
}

async function matchLineProduct(row) {
  row.matching = true
  try {
    const res = await matchInvoiceProduct({
      model: row.model,
      color: row.color,
      size: row.length,
      unit: row.net_weight_grams,
    })
    if (!res.is_unique) {
      ElMessage.warning((res.matches || []).length ? '当前条件匹配到多个产品，请继续确认规格' : '当前条件未匹配到产品')
      return
    }
    const item = res.item
    row.product_id = item.product_id
    row.sku_id = item.sku_id
    row.product_name = item.product_name
    row.product_display = item.product_display
    row.price_source = item.price_source || 'missing'
    if (item.price_per_piece) {
      row.price_per_piece = Number(item.price_per_piece)
      updateLineTotal(row)
    }
  } finally {
    row.matching = false
  }
}

function updateLineTotal(row) {
  row.total_price = Number(row.quantity || 0) * Number(row.price_per_piece || 0)
}

function buildPayload() {
  return {
    customer_id: form.customer_id,
    customer_name: form.customer_name,
    invoice_date: form.invoice_date,
    currency: form.currency || 'USD',
    remark: form.remark,
    items: form.items.map(line => ({
      product_id: line.product_id,
      sku_id: line.sku_id,
      product_name: line.product_name,
      product_display: line.product_display,
      net_weight_grams: line.net_weight_grams,
      curl: line.curl || null,
      model: line.model,
      color: line.color,
      length: line.length,
      quantity: line.quantity,
      price_per_piece: line.price_per_piece,
      price_source: line.price_source || 'manual',
    })),
  }
}

async function saveDraft() {
  const saved = form.id
    ? await updateInvoice(form.id, buildPayload())
    : await createInvoice(buildPayload())
  resetForm(saved)
  ElMessage.success('发票已保存')
  loadInvoices()
}

async function saveAndValidate() {
  await saveDraft()
  const res = await validateInvoice(form.id)
  if (res.ok) {
    ElMessage.success('校验通过，可以同步小满')
  } else {
    showIssues(res.issues)
  }
  loadInvoices()
}

async function validateAndSync(id) {
  const validation = await validateInvoice(id)
  if (!validation.ok) {
    showIssues(validation.issues)
    return
  }
  const result = await syncInvoice(id)
  if (result.ok) {
    ElMessage.success('已同步到小满')
  } else {
    ElMessage.warning(result.message || '小满同步未完成')
  }
  loadInvoices()
}

function showIssues(issues = []) {
  const html = issues.map(i => `<p>${i.field}: ${i.message}</p>`).join('') || '校验未通过'
  ElMessageBox.alert(html, '同步前校验', { dangerouslyUseHTMLString: true, confirmButtonText: '知道了' })
}

async function exportExcel(id) {
  const res = await downloadInvoiceExcel(id)
  downloadBlob(res, 'invoice.xlsx')
}

async function exportPdf(id) {
  const res = await downloadInvoicePdf(id)
  downloadBlob(res, 'invoice.pdf')
}

function downloadBlob(res, fallbackName) {
  const blob = new Blob([res.data], { type: res.headers['content-type'] })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = fallbackName
  link.click()
  URL.revokeObjectURL(url)
}

function openPrint(id) {
  window.open(getInvoicePrintUrl(id), '_blank')
}

function money(value) {
  return Number(value || 0).toFixed(2)
}

function statusText(status) {
  return { draft: '草稿', ready: '可同步', synced: '已同步', sync_failed: '同步失败' }[status] || status
}

function statusType(status) {
  return { draft: 'info', ready: 'success', synced: 'success', sync_failed: 'danger' }[status] || 'info'
}

function syncText(status) {
  return { not_synced: '未同步', synced: '已同步', sync_failed: '失败' }[status] || status
}

function syncType(status) {
  return { not_synced: 'info', synced: 'success', sync_failed: 'danger' }[status] || 'info'
}
</script>

<style scoped>
.invoice-page {
  --invoice-ease-out: cubic-bezier(0.23, 1, 0.32, 1);
  --invoice-ease-drawer: cubic-bezier(0.32, 0.72, 0, 1);
  --invoice-border: var(--border-color, #e2e5ef);
  --invoice-border-hover: var(--border-hover, #c5cce0);
  --invoice-muted: var(--text-secondary, #4a5568);
  --invoice-placeholder: var(--text-muted, #a0aec0);
  --invoice-ink: var(--text-primary, #1a1a2e);
  --invoice-surface: var(--card-bg, #ffffff);
  --invoice-soft: var(--table-header-bg, #fafbfe);
  --invoice-gold: var(--color-primary, #d4941c);
  --invoice-gold-light: var(--color-primary-light, rgba(212, 148, 28, 0.08));
  padding: 24px 28px;
  color: var(--invoice-ink);
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
  animation: invoice-enter 220ms var(--invoice-ease-out) both;
}

.page-header h2 {
  margin: 0 0 6px;
  font-family: var(--font-display);
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 0;
}

.page-header p {
  margin: 0;
  font-size: 14px;
  font-weight: 500;
  color: var(--invoice-muted);
}

.primary-action {
  min-width: 112px;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(150px, 1fr));
  gap: 12px;
  margin-bottom: 14px;
  animation: invoice-enter 220ms var(--invoice-ease-out) 70ms both;
}

.summary-card {
  display: flex;
  min-height: 76px;
  flex-direction: column;
  justify-content: center;
  gap: 8px;
  padding: 14px 16px;
  border: 1px solid var(--invoice-border);
  border-radius: 12px;
  background: var(--invoice-surface);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  transition: transform 160ms var(--invoice-ease-out), border-color 160ms var(--invoice-ease-out), background-color 160ms var(--invoice-ease-out);
}

.summary-card span {
  color: var(--invoice-muted);
  font-size: 13px;
}

.summary-card strong {
  font-family: var(--font-display);
  font-size: 24px;
  font-weight: 700;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.summary-card.emphasis {
  border-color: rgba(212, 148, 28, 0.35);
  background: linear-gradient(180deg, #ffffff 0%, rgba(212, 148, 28, 0.08) 100%);
}

.invoice-panel {
  border: 1px solid var(--invoice-border);
  border-radius: 12px;
  background: var(--invoice-surface);
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.05);
  animation: invoice-enter 220ms var(--invoice-ease-out) 140ms both;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px;
  border-bottom: 1px solid var(--invoice-border);
  background: var(--invoice-soft);
}

.invoice-table,
.line-table {
  width: 100%;
}

.row-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
}

.empty-state {
  display: flex;
  min-height: 180px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--invoice-muted);
}

.empty-state strong {
  color: var(--invoice-ink);
  font-size: 16px;
}

.pagination-bar {
  display: flex;
  justify-content: flex-end;
  padding: 16px 0;
}

.invoice-form {
  padding-right: 12px;
}

.invoice-form :deep(.el-form-item__label) {
  color: var(--invoice-muted);
  font-weight: 600;
}

.form-grid {
  display: grid;
  grid-template-columns: minmax(280px, 2fr) minmax(180px, 1fr) minmax(120px, 0.6fr);
  gap: 4px 16px;
  padding: 2px 2px 14px;
  border-bottom: 1px solid var(--invoice-border);
}

.form-grid .wide {
  grid-column: 1 / -1;
}

.line-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 18px 0 12px;
}

.line-header span {
  margin-left: 10px;
  color: var(--invoice-muted);
  font-size: 13px;
}

.line-table-wrap {
  overflow-x: auto;
  border: 1px solid var(--invoice-border);
  border-radius: 12px;
}

.product-cell {
  display: flex;
  min-height: 28px;
  align-items: center;
  gap: 8px;
  transition: opacity 160ms var(--invoice-ease-out), transform 160ms var(--invoice-ease-out);
  will-change: opacity, transform;
}

.product-cell.is-pending {
  color: var(--invoice-placeholder);
}

.product-cell.is-matched {
  color: var(--invoice-ink);
  transform: translateY(0);
}

.drawer-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 0 2px;
}

.total-box {
  color: var(--invoice-muted);
  font-variant-numeric: tabular-nums;
}

.total-box strong {
  color: var(--invoice-ink);
  font-size: 18px;
}

.invoice-page :deep(.el-drawer__body) {
  padding-top: 18px;
}

.invoice-page :deep(.el-drawer__footer) {
  border-top: 1px solid var(--invoice-border);
  background: rgba(250, 251, 254, 0.96);
}

.invoice-page :deep(.el-button) {
  transition: transform 140ms var(--invoice-ease-out), opacity 140ms var(--invoice-ease-out), background-color 140ms var(--invoice-ease-out), border-color 140ms var(--invoice-ease-out);
}

.invoice-page :deep(.el-button:active) {
  transform: scale(0.97);
}

@media (hover: hover) and (pointer: fine) {
  .summary-card:hover {
    border-color: var(--invoice-border-hover);
    box-shadow: 0 12px 28px rgba(15, 23, 42, 0.08);
    transform: translateY(-2px);
  }
}

@keyframes invoice-enter {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (prefers-reduced-motion: reduce) {
  .page-header,
  .summary-grid,
  .invoice-panel {
    animation: none;
  }

  .summary-card,
  .product-cell,
  .invoice-page :deep(.el-button) {
    transition: opacity 120ms var(--invoice-ease-out), background-color 120ms var(--invoice-ease-out), border-color 120ms var(--invoice-ease-out);
  }

  .invoice-page :deep(.el-button:active),
  .summary-card:hover {
    transform: none;
  }
}

@media (max-width: 900px) {
  .page-header,
  .toolbar,
  .drawer-footer {
    align-items: stretch;
    flex-direction: column;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }

  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 560px) {
  .summary-grid {
    grid-template-columns: 1fr;
  }
}
</style>
