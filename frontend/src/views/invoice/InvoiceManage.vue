<template>
  <div class="invoice-page">
    <div class="page-header">
      <div>
        <h2>订单发票管理</h2>
        <p>客户发票、产品明细、价格管控、导出与小满同步集中处理。</p>
      </div>
      <div class="header-actions">
        <el-button type="primary" class="primary-action" @click="openCreate('stock')">
          <el-icon><Plus /></el-icon>
          新建库存单
        </el-button>
        <el-button @click="openCreate('production')">
          <el-icon><Plus /></el-icon>
          新建生产单
        </el-button>
      </div>
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
        <el-select v-model="filters.order_type" clearable placeholder="订单类型" style="width: 130px">
          <el-option label="库存单" value="stock" />
          <el-option label="生产单" value="production" />
        </el-select>
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
        <el-table-column label="类型" min-width="90" max-width="110">
          <template #default="{ row }">
            <el-tag :type="row.order_type === 'production' ? 'warning' : 'info'" effect="plain">
              {{ row.order_type === 'production' ? '生产单' : '库存单' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="customer_name" label="客户" min-width="200" max-width="340" show-overflow-tooltip />
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
        <el-table-column label="同步" min-width="110" max-width="150">
          <template #default="{ row }">
            <el-tag :type="syncType(row.sync_status)" effect="plain">{{ syncText(row.sync_status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="330" max-width="390" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button link type="primary" @click="openEdit(row.id)">
                <el-icon><Edit /></el-icon>
                编辑
              </el-button>
              <el-button link @click="exportExcel(row)">
                <el-icon><Download /></el-icon>
                Excel
              </el-button>
              <el-button link @click="exportPdf(row)">
                <el-icon><Download /></el-icon>
                PDF
              </el-button>
              <el-button link @click="openPrint(row.id)">
                <el-icon><Printer /></el-icon>
                打印
              </el-button>
              <el-button v-permission="'invoice:sync'" link type="warning" @click="validateAndSync(row.id)">
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

    <el-drawer v-model="drawerVisible" :title="drawerTitle" size="94%">
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
                  :label="customerLabel(customer)"
                  :value="customer"
                />
              </el-select>
              <div v-if="customerRule" class="rule-badge">
                该客户价格规则：{{ describeCustomerRule(customerRule) }}
              </div>
            </el-form-item>
            <el-form-item label="日期" required>
              <el-date-picker v-model="form.invoice_date" value-format="YYYY-MM-DD" style="width: 100%" />
            </el-form-item>
            <el-form-item label="币种">
              <el-input v-model="form.currency" maxlength="16" />
            </el-form-item>
            <el-form-item label="联系人">
              <el-input v-model="form.contact_name" maxlength="100" placeholder="To" />
            </el-form-item>
            <el-form-item label="电话">
              <el-input v-model="form.contact_phone" maxlength="50" placeholder="TEL/Fax" />
            </el-form-item>
            <el-form-item label="邮箱">
              <el-input v-model="form.contact_email" maxlength="100" placeholder="E-mail" />
            </el-form-item>
            <el-form-item label="收货地址" class="wide">
              <el-input v-model="form.delivery_address" maxlength="500" placeholder="Delivery address" />
            </el-form-item>
            <el-form-item label="业务员">
              <el-input v-model="form.sales_user_name" maxlength="50" placeholder="From" />
            </el-form-item>
            <el-form-item label="业务电话">
              <el-input v-model="form.sales_phone" maxlength="50" />
            </el-form-item>
            <el-form-item label="业务邮箱">
              <el-input v-model="form.sales_email" maxlength="100" />
            </el-form-item>
            <el-form-item label="快递渠道">
              <el-input v-model="form.express_channel" maxlength="32" placeholder="如 DHL" />
            </el-form-item>
            <el-form-item label="运费">
              <el-input-number v-model="form.shipping_fee" :min="0" :precision="2" controls-position="right" style="width: 100%" />
            </el-form-item>
            <el-form-item label="附加费">
              <div class="surcharge-row">
                <el-input v-model="form.surcharge_name" maxlength="64" placeholder="名目，如 Paypal Surcharge" />
                <el-input-number v-model="form.surcharge_amount" :min="0" :precision="2" controls-position="right" />
              </div>
            </el-form-item>
            <el-form-item label="付款条款" class="wide">
              <el-input v-model="form.payment_term" maxlength="200" placeholder="Payment Term，如 TT 20%" />
            </el-form-item>
            <el-form-item label="备注" class="wide">
              <el-input v-model="form.remark" type="textarea" :rows="2" maxlength="500" />
            </el-form-item>
          </div>

          <div class="line-header">
            <div>
              <strong>产品明细</strong>
              <span v-if="isProduction">生产单：关键词下拉可选可输，已有属性直接选，没有就按输入沉淀新产品。</span>
              <span v-else>四个关键词选择完整后自动匹配唯一 Product_name。</span>
            </div>
            <el-button @click="addLine">
              <el-icon><Plus /></el-icon>
              添加明细
            </el-button>
          </div>

          <div class="line-table-wrap">
            <el-table :data="form.items" border class="list-table line-table">
              <el-table-column label="#" type="index" min-width="48" max-width="60" fixed />

              <el-table-column v-if="isProduction" label="Product" min-width="230" max-width="320">
                <template #default="{ row }">
                  <el-select
                    v-model="row.product_display"
                    filterable
                    allow-create
                    default-first-option
                    placeholder="系列描述，可输入"
                    @change="onCustomFieldChange(row)"
                  >
                    <el-option v-for="v in entryOptions.displays" :key="v" :label="v" :value="v" />
                  </el-select>
                </template>
              </el-table-column>

              <el-table-column label="Model" min-width="150" max-width="220">
                <template #default="{ row }">
                  <el-select
                    v-if="isProduction"
                    v-model="row.model"
                    filterable
                    allow-create
                    clearable
                    default-first-option
                    placeholder="可选"
                    @change="onCustomFieldChange(row)"
                  >
                    <el-option v-for="v in entryOptions.models" :key="v" :label="v" :value="v" />
                  </el-select>
                  <el-select
                    v-else
                    v-model="row.model"
                    filterable
                    placeholder="Model"
                    @visible-change="v => v && loadLineOptions(row)"
                    @change="onLineFilterChange(row)"
                  >
                    <el-option v-for="v in row.options.models" :key="v" :label="v" :value="v" />
                  </el-select>
                </template>
              </el-table-column>

              <el-table-column label="Color" min-width="150" max-width="220">
                <template #default="{ row }">
                  <el-select
                    v-if="isProduction"
                    v-model="row.color"
                    filterable
                    allow-create
                    default-first-option
                    placeholder="Color"
                    @change="onCustomFieldChange(row)"
                  >
                    <el-option v-for="v in entryOptions.colors" :key="v" :label="v" :value="v" />
                  </el-select>
                  <el-select
                    v-else
                    v-model="row.color"
                    filterable
                    placeholder="Color"
                    @visible-change="v => v && loadLineOptions(row)"
                    @change="onLineFilterChange(row)"
                  >
                    <el-option v-for="v in row.options.colors" :key="v" :label="v" :value="v" />
                  </el-select>
                </template>
              </el-table-column>

              <el-table-column label="Length" min-width="130" max-width="180">
                <template #default="{ row }">
                  <el-select
                    v-if="isProduction"
                    v-model="row.length"
                    filterable
                    allow-create
                    default-first-option
                    placeholder="Length"
                    @change="onCustomFieldChange(row)"
                  >
                    <el-option v-for="v in entryOptions.sizes" :key="v" :label="v" :value="v" />
                  </el-select>
                  <el-select
                    v-else
                    v-model="row.length"
                    filterable
                    placeholder="Length"
                    @visible-change="v => v && loadLineOptions(row)"
                    @change="onLineFilterChange(row)"
                  >
                    <el-option v-for="v in row.options.sizes" :key="v" :label="v" :value="v" />
                  </el-select>
                </template>
              </el-table-column>

              <el-table-column label="Net Weight Grams" min-width="150" max-width="210">
                <template #default="{ row }">
                  <el-select
                    v-if="isProduction"
                    v-model="row.net_weight_grams"
                    filterable
                    allow-create
                    default-first-option
                    placeholder="Unit"
                    @change="onCustomFieldChange(row)"
                  >
                    <el-option v-for="v in entryOptions.units" :key="v" :label="v" :value="v" />
                  </el-select>
                  <el-select
                    v-else
                    v-model="row.net_weight_grams"
                    filterable
                    placeholder="Unit"
                    @visible-change="v => v && loadLineOptions(row)"
                    @change="onLineFilterChange(row)"
                  >
                    <el-option v-for="v in row.options.units" :key="v" :label="v" :value="v" />
                  </el-select>
                </template>
              </el-table-column>

              <el-table-column v-if="!isProduction" label="Product_name" min-width="280" max-width="420" show-overflow-tooltip>
                <template #default="{ row }">
                  <div :class="['product-cell', row.product_name ? 'is-matched' : 'is-pending']">
                    <span>{{ row.product_name || '待匹配' }}</span>
                    <el-tag v-if="row.sku_id" size="small" effect="plain">SKU {{ row.sku_id }}</el-tag>
                    <el-tag v-else-if="row.matching" size="small" type="info" effect="plain">匹配中</el-tag>
                  </div>
                </template>
              </el-table-column>

              <el-table-column label="Curl" min-width="130" max-width="180">
                <template #default="{ row }">
                  <el-select v-model="row.curl" clearable placeholder="可选">
                    <el-option v-for="v in CURL_OPTIONS" :key="v" :label="v" :value="v" />
                  </el-select>
                </template>
              </el-table-column>

              <el-table-column label="标准价" min-width="120" max-width="170" align="right">
                <template #default="{ row }">
                  <span v-if="row.standard_price != null" class="std-price">
                    {{ money4(row.standard_price) }}
                    <el-tooltip v-if="row.color_type_source === 'inferred'" content="该色号未登记色型映射，价格按命名规则推断的色型取得，请人工核对">
                      <el-tag size="small" type="warning" effect="plain">色型推断</el-tag>
                    </el-tooltip>
                  </span>
                  <el-tag v-else size="small" type="warning" effect="plain">无标准价</el-tag>
                </template>
              </el-table-column>

              <el-table-column label="Quantity" min-width="120" max-width="160">
                <template #default="{ row }">
                  <el-input-number v-model="row.quantity" :min="1" :precision="0" controls-position="right" @change="updateLineTotal(row)" />
                </template>
              </el-table-column>

              <el-table-column label="Price/Piece（客户价）" min-width="170" max-width="220">
                <template #default="{ row }">
                  <div :class="['price-cell', row.price_source === 'manual' ? 'is-manual' : '']">
                    <el-input-number v-model="row.price_per_piece" :min="0.01" :precision="4" controls-position="right" @change="onPriceInput(row)" />
                    <el-tag v-if="row.price_source === 'manual'" size="small" type="warning" effect="plain">手改</el-tag>
                  </div>
                </template>
              </el-table-column>

              <el-table-column label="TotalPrice" min-width="120" max-width="170" align="right">
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

          <el-collapse class="internal-collapse">
            <el-collapse-item title="内部结算（不出现在客户发票）" name="internal">
              <div class="form-grid">
                <el-form-item label="付款方式">
                  <el-input v-model="form.internal_payment_method" maxlength="32" placeholder="如 TT / Paypal" />
                </el-form-item>
                <el-form-item label="折扣">
                  <el-input-number v-model="form.internal_discount" :precision="2" controls-position="right" style="width: 100%" />
                </el-form-item>
                <el-form-item label="配件">
                  <el-input-number v-model="form.internal_accessory" :precision="2" controls-position="right" style="width: 100%" />
                </el-form-item>
                <el-form-item label="实际到账">
                  <el-input-number v-model="form.internal_received" :precision="2" controls-position="right" style="width: 100%" />
                </el-form-item>
                <el-form-item label="尾款">
                  <el-input-number v-model="form.internal_balance" :precision="2" controls-position="right" style="width: 100%" />
                </el-form-item>
                <el-form-item label="发货方式">
                  <el-input v-model="form.internal_shipping_type" maxlength="32" placeholder="如 普货" />
                </el-form-item>
              </div>
            </el-collapse-item>
          </el-collapse>
        </el-form>
      </template>

      <template #footer>
        <div class="drawer-footer">
          <div class="total-box">
            <span>货款 {{ money(formProductTotal) }} + 运费 {{ money(form.shipping_fee) }} + 附加费 {{ money(form.surcharge_amount) }}</span>
            <span class="grand">Total: <strong>{{ form.currency }} {{ money(formTotal) }}</strong></span>
          </div>
          <div>
            <el-button @click="drawerVisible = false">取消</el-button>
            <el-button v-permission="'invoice:write'" @click="saveDraft">保存</el-button>
            <el-button v-permission="'invoice:write'" type="primary" @click="saveAndValidate">保存并校验</el-button>
          </div>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Delete, Download, Edit, Plus, Printer, Refresh, Search } from '@element-plus/icons-vue'
import {
  downloadInvoiceExcel,
  downloadInvoicePdf,
  fetchInvoicePrintHtml,
  listInvoices,
  syncInvoice,
  validateInvoice,
} from '@/api/invoice'
import { CURL_OPTIONS, customerLabel, describeCustomerRule, useInvoiceEditor } from './composables/useInvoiceEditor'

const loading = ref(false)
const invoices = ref([])
const filters = reactive({ keyword: '', status: '', order_type: '' })
const pagination = reactive({ page: 1, page_size: 20, total: 0 })

const {
  drawerVisible,
  customerLoading,
  customerOptions,
  selectedCustomer,
  customerRule,
  entryOptions,
  form,
  formProductTotal,
  formTotal,
  isProduction,
  searchCustomers,
  onCustomerChange,
  openCreate,
  openEdit,
  addLine,
  removeLine,
  loadLineOptions,
  onLineFilterChange,
  onCustomFieldChange,
  onPriceInput,
  updateLineTotal,
  saveDraft,
  saveAndValidate,
  showIssues,
} = useInvoiceEditor({ onSaved: () => loadInvoices() })

const drawerTitle = computed(() => {
  const typeLabel = form.order_type === 'production' ? '生产单' : '库存单'
  return form.id ? `编辑${typeLabel} ${form.invoice_no}` : `新建${typeLabel}`
})

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

async function loadInvoices() {
  loading.value = true
  try {
    const params = { ...filters, page: pagination.page, page_size: pagination.page_size }
    if (!params.order_type) delete params.order_type
    const res = await listInvoices(params)
    invoices.value = res.items || []
    pagination.total = res.total || 0
  } finally {
    loading.value = false
  }
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

async function exportExcel(row) {
  const res = await downloadInvoiceExcel(row.id)
  downloadBlob(res, `${row.invoice_no || 'invoice'}.xlsx`)
}

async function exportPdf(row) {
  const res = await downloadInvoicePdf(row.id)
  downloadBlob(res, `${row.invoice_no || 'invoice'}.pdf`)
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

async function openPrint(id) {
  // 新标签直连后端会因不带 Authorization 而 403，先鉴权取回 HTML 再本地打开
  const html = await fetchInvoicePrintHtml(id)
  const blob = new Blob([html], { type: 'text/html' })
  const url = URL.createObjectURL(blob)
  window.open(url, '_blank')
  setTimeout(() => URL.revokeObjectURL(url), 60000)
}

function money(value) {
  return Number(value || 0).toFixed(2)
}

function money4(value) {
  return Number(value || 0).toFixed(4)
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

<style scoped src="./invoice-manage.css"></style>
