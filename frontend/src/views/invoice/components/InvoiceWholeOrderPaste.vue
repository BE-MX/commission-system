<template>
  <el-dialog
    v-model="visible"
    title="从 Excel 整单粘贴"
    width="min(1180px, 94vw)"
    destroy-on-close
    class="whole-order-paste-dialog"
  >
    <div v-if="step === 1" class="paste-stage">
      <div class="stage-heading">
        <div>
          <h3>复制 Excel 发票整段内容，粘贴到下方</h3>
          <p>一次识别：客户、电话、邮箱、收货地址、产品明细行、折扣总价、包装费用、运费、手续费、付款方式/快递渠道；hair/tool/total/final 行自动忽略。</p>
        </div>
      </div>
      <el-input
        v-model="pasteText"
        type="textarea"
        :rows="12"
        resize="vertical"
        placeholder="在 Excel 中选中整段内容（含产品明细，如 C6:I23），复制后在这里按 Ctrl+V 粘贴"
        @paste="pasteError = ''"
      />
      <el-alert v-if="pasteError" :title="pasteError" type="error" show-icon :closable="false" />
    </div>

    <div v-else class="preview-stage">
      <h4 class="section-heading">订单字段</h4>
      <el-table :data="fieldRows" border size="small" class="list-table">
        <el-table-column prop="label" label="字段" width="120" />
        <el-table-column label="识别内容">
          <template #default="{ row }"><span class="value-cell">{{ row.value || '—' }}</span></template>
        </el-table-column>
        <el-table-column label="状态" width="130">
          <template #default="{ row }"><el-tag :type="row.statusType" effect="plain">{{ row.statusText }}</el-tag></template>
        </el-table-column>
      </el-table>
      <el-alert
        v-if="parsed?.ignored_rows"
        :title="`已按规则忽略 ${parsed.ignored_rows} 行（hair/tool/total/final 关键词）`"
        type="info"
        show-icon
        :closable="false"
      />

      <template v-if="productPreview">
        <div class="section-heading product-heading">
          <h4>产品明细（{{ previewRows.length }} 行）</h4>
          <div class="result-summary">
            <el-button link @click="locateStatus('passed')"><el-tag type="success" effect="plain">通过 {{ resultCounts.passed }}</el-tag></el-button>
            <el-button link @click="locateStatus('warning')"><el-tag type="warning" effect="plain">提醒 {{ resultCounts.warning }}</el-tag></el-button>
            <el-button link @click="locateStatus('blocked')"><el-tag type="danger" effect="plain">待处理 {{ resultCounts.blocked }}</el-tag></el-button>
          </div>
        </div>
        <!-- 与「从 Excel 粘贴」同款的校验/修正表：候选选择、定制产品确认、行内提示 -->
        <div class="preview-table-wrap">
          <el-table
            ref="previewTable"
            :data="previewRows"
            border
            max-height="380"
            highlight-current-row
            class="list-table preview-table"
          >
            <el-table-column prop="source_row" label="行" min-width="56" fixed />
            <el-table-column label="状态" min-width="82" fixed>
              <template #default="{ row }">
                <el-tag :type="statusType(row.status)" effect="plain">{{ statusText(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="Product" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">{{ row.normalized.product }}</template>
            </el-table-column>
            <el-table-column label="Length" min-width="76">
              <template #default="{ row }">{{ row.normalized.length }}</template>
            </el-table-column>
            <el-table-column label="Color" min-width="86">
              <template #default="{ row }">{{ row.normalized.color }}</template>
            </el-table-column>
            <el-table-column label="Weight" min-width="82">
              <template #default="{ row }">{{ row.normalized.weight }}</template>
            </el-table-column>
            <el-table-column label="数量" min-width="66" align="right">
              <template #default="{ row }">{{ row.normalized.quantity }}</template>
            </el-table-column>
            <el-table-column label="Excel 成交价" min-width="106" align="right">
              <template #default="{ row }">{{ displayUnitPrice(row.normalized.unit_price) }}</template>
            </el-table-column>
            <el-table-column label="客户价" min-width="96" align="right">
              <template #default="{ row }">{{ nullableMoney(row.customer_price) }}</template>
            </el-table-column>
            <el-table-column class-name="table-action-column" label="匹配结果 / 处理" min-width="280" fixed="right">
              <template #default="{ row }">
                <div class="resolution-cell">
                  <template v-if="row.candidates?.length">
                    <el-select
                      v-model="row._candidateKey"
                      placeholder="请选择正确的产品和 SKU"
                      @change="key => applyCandidate(row, key)"
                    >
                      <el-option
                        v-for="candidate in row.candidates"
                        :key="candidateKey(candidate)"
                        :label="candidateLabel(candidate)"
                        :value="candidateKey(candidate)"
                      />
                    </el-select>
                  </template>
                  <span v-else-if="row.matched_product" class="matched-product">
                    {{ candidateLabel(row.matched_product) }}
                  </span>
                  <el-button
                    v-if="row.can_create_custom && !row._useCustom"
                    link
                    type="primary"
                    @click="confirmCustom(row)"
                  >
                    作为定制产品
                  </el-button>
                  <el-text v-if="row.candidates?.length && row.matched_product?.stock_warning" type="warning">
                    {{ row.matched_product.stock_warning }}
                  </el-text>
                  <span v-if="row._useCustom" class="custom-confirmed">已确认作为定制产品</span>
                  <ul v-if="row.errors?.length || row.warnings?.length" class="row-messages">
                    <li v-for="message in row.errors" :key="`error-${message}`" class="error-text">{{ message }}</li>
                    <li v-for="message in row.warnings" :key="`warning-${message}`">{{ message }}</li>
                  </ul>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <el-alert
          v-if="hasBlockedRows"
          title="仍有待处理的产品行。请选择正确的产品/SKU，或在生产单中明确确认定制产品。"
          type="error"
          show-icon
          :closable="false"
        />
      </template>
    </div>

    <template #footer>
      <div class="dialog-footer">
        <el-button v-if="step === 2" @click="step = 1">返回重新粘贴</el-button>
        <span class="footer-spacer" />
        <el-button @click="visible = false">取消</el-button>
        <el-button v-if="step === 1" type="primary" :loading="working" @click="runParse">解析</el-button>
        <el-button v-else type="primary" :disabled="hasBlockedRows" @click="apply">应用到当前订单</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { previewInvoiceImport } from '@/api/invoice'
import { parseWholeOrderClipboard } from '../composables/useInvoiceWholeOrderPaste'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  // matchCustomer(name) → { status: 'matched', option } | { status: 'multiple', count } | { status: 'none' }
  matchCustomer: { type: Function, required: true },
  customerId: { type: [String, Number], default: '' },
  orderType: { type: String, required: true },
  currency: { type: String, required: true },
})
const emit = defineEmits(['update:modelValue', 'apply'])

const step = ref(1)
const pasteText = ref('')
const pasteError = ref('')
const working = ref(false)
const parsed = ref(null)
const customerMatch = ref(null)
const productPreview = ref(null)
const previewTable = ref(null)

const visible = computed({
  get: () => props.modelValue,
  set: value => emit('update:modelValue', value),
})

watch(() => props.modelValue, value => {
  if (!value) return
  step.value = 1
  pasteText.value = ''
  pasteError.value = ''
  parsed.value = null
  customerMatch.value = null
  productPreview.value = null
})

const fieldRows = computed(() => {
  const p = parsed.value
  if (!p) return []
  const rows = []
  const customerRow = { label: '客户', value: p.customer_name }
  if (!p.customer_name) rows.push({ ...customerRow, statusText: '未识别', statusType: 'info' })
  else if (customerMatch.value?.status === 'matched') rows.push({ ...customerRow, statusText: `已匹配：${customerMatch.value.option.company_name}`, statusType: 'success' })
  else if (customerMatch.value?.status === 'multiple') rows.push({ ...customerRow, statusText: `${customerMatch.value.count} 个候选，需手选`, statusType: 'warning' })
  else rows.push({ ...customerRow, statusText: '无匹配，需手选', statusType: 'warning' })
  const text = (label, value) => rows.push({ label, value, statusText: value ? '将填入' : '未识别', statusType: value ? 'success' : 'info' })
  text('电话', p.contact_phone)
  text('邮箱', p.contact_email)
  text('收货地址', p.delivery_address)
  const amount = (label, value) => rows.push({ label, value: value == null ? '' : String(value), statusText: value == null ? '未识别' : '将填入', statusType: value == null ? 'info' : 'success' })
  amount('折扣总价', p.discount_total)
  amount('包装费用', p.packaging_fee)
  amount('运费', p.shipping_fee)
  amount('手续费', p.handling_fee)
  rows.push({
    label: '付款方式',
    value: p.payment_method || p.payment_raw,
    statusText: p.payment_method ? '将填入' : '未匹配，需手选',
    statusType: p.payment_method ? 'success' : 'warning',
  })
  if (p.express_channel) rows.push({ label: '快递渠道', value: p.express_channel, statusText: '将填入', statusType: 'success' })
  return rows
})

const previewRows = computed(() => productPreview.value?.rows || [])
const resultCounts = computed(() => previewRows.value.reduce((counts, row) => {
  counts.total += 1
  counts[row.status] += 1
  return counts
}, { total: 0, passed: 0, warning: 0, blocked: 0 }))
const hasBlockedRows = computed(() => resultCounts.value.blocked > 0)

async function runParse() {
  pasteError.value = ''
  try {
    parsed.value = parseWholeOrderClipboard(pasteText.value)
  } catch (error) {
    pasteError.value = error.message || '无法解析粘贴内容'
    return
  }
  working.value = true
  try {
    // 先匹配客户：客户价/价格规则要在产品校验时按正确客户取价
    customerMatch.value = null
    if (parsed.value.customer_name) customerMatch.value = await props.matchCustomer(parsed.value.customer_name)
    productPreview.value = null
    if (parsed.value.product_rows.length) {
      const customerId = customerMatch.value?.status === 'matched'
        ? customerMatch.value.option.company_id
        : props.customerId
      productPreview.value = await previewInvoiceImport({
        customer_id: customerId || undefined,
        order_type: props.orderType,
        currency: props.currency,
        rows: parsed.value.product_rows,
      })
    }
    step.value = 2
  } catch (error) {
    pasteError.value = error?.response?.data?.detail || error?.message || '校验失败，请保留当前内容后重试'
  } finally {
    working.value = false
  }
}

function candidateKey(candidate) {
  return `${candidate.product_id}:${candidate.sku_id ?? ''}`
}

function candidateLabel(candidate) {
  const sku = candidate.sku_id == null ? '无可用 SKU' : `SKU ${candidate.sku_id}`
  return `${candidate.product_name || candidate.product_display} · ${sku}`
}

function applyCandidate(row, key) {
  const candidate = row.candidates.find(item => candidateKey(item) === key)
  if (!candidate) return
  row.matched_product = candidate
  row._useCustom = false
  if (candidate.sku_id == null) {
    row.errors = [`第 ${row.source_row} 行所选产品没有可用 SKU`]
    row.status = 'blocked'
    return
  }
  row.errors = []
  row.status = row.warnings?.length ? 'warning' : 'passed'
}

function confirmCustom(row) {
  row.matched_product = null
  row.errors = []
  row._candidateKey = ''
  row._useCustom = true
  row.status = row.warnings?.length ? 'warning' : 'passed'
}

function locateStatus(status) {
  const index = previewRows.value.findIndex(row => row.status === status)
  if (index < 0) {
    ElMessage.info('当前没有该状态的明细')
    return
  }
  const row = previewRows.value[index]
  previewTable.value?.setCurrentRow(row)
  previewTable.value?.scrollTo({ top: index * 48 })
}

function statusType(status) {
  return { passed: 'success', warning: 'warning', blocked: 'danger' }[status] || 'info'
}

function statusText(status) {
  return { passed: '通过', warning: '提醒', blocked: '待处理' }[status] || status
}

function money(value) {
  return Number(value || 0).toFixed(2)
}

function nullableMoney(value) {
  return value == null ? '—' : money(value)
}

function displayUnitPrice(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(2) : String(value || '—')
}

function apply() {
  emit('apply', {
    ...parsed.value,
    _customerOption: customerMatch.value?.status === 'matched' ? customerMatch.value.option : null,
    productPreview: productPreview.value
      ? { rows: previewRows.value, fingerprint: productPreview.value.batch_fingerprint }
      : null,
  })
  visible.value = false
}
</script>

<style scoped>
.paste-stage, .preview-stage { display: grid; gap: 14px; }
.stage-heading h3 { margin: 0 0 6px; font-size: 16px; color: var(--text-primary); }
.stage-heading p { margin: 0; color: var(--text-secondary); line-height: 1.6; }
.section-heading { margin: 0; font-size: 14px; color: var(--text-primary); }
.product-heading { display: flex; align-items: center; justify-content: space-between; margin-top: 6px; }
.product-heading h4 { margin: 0; font-size: 14px; color: var(--text-primary); }
.result-summary { display: flex; align-items: center; gap: 10px; }
.value-cell { white-space: pre-wrap; overflow-wrap: anywhere; }
.preview-table-wrap { overflow: hidden; border-radius: 8px; }
.resolution-cell { display: grid; gap: 6px; }
.matched-product, .custom-confirmed { color: var(--text-secondary); }
.custom-confirmed { color: var(--color-success-text); }
.row-messages { margin: 0; padding-left: 18px; color: var(--color-warning-text); font-size: 12px; line-height: 1.45; }
.row-messages .error-text { color: var(--color-danger-text); }
.dialog-footer { display: flex; align-items: center; width: 100%; }
.footer-spacer { flex: 1; }
</style>
