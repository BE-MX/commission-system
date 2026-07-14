<template>
  <el-dialog
    v-model="visible"
    title="从 Excel 粘贴产品明细"
    width="min(1180px, 94vw)"
    destroy-on-close
    class="invoice-paste-dialog"
  >
    <el-steps :active="step - 1" finish-status="success" align-center class="import-steps">
      <el-step title="粘贴数据" />
      <el-step title="校验与修正" />
      <el-step title="完成" />
    </el-steps>

    <div class="context-bar">
      <span><small>客户</small>{{ customerName || customerId }}</span>
      <span><small>订单类型</small>{{ orderType === 'production' ? '生产单' : '库存单' }}</span>
      <span><small>币种</small>{{ currency }}</span>
    </div>

    <div v-if="step === 1" class="paste-stage">
      <div class="stage-heading">
        <div>
          <h3>复制 Excel 中的产品明细，粘贴到下方</h3>
          <p>支持 Product、Length、Color、Weight、Quantity、Unit Price 六列；多余列会自动忽略。</p>
        </div>
        <el-tag effect="plain">最多 200 行</el-tag>
      </div>
      <el-input
        v-model="pasteText"
        type="textarea"
        :rows="12"
        resize="vertical"
        placeholder="在 Excel 中选中包含表头的数据，复制后在这里按 Ctrl+V 粘贴"
        @paste="pasteError = ''"
      />
      <el-alert v-if="pasteError" :title="pasteError" type="error" show-icon :closable="false" />
    </div>

    <div v-else-if="step === 2" class="preview-stage">
      <div class="result-summary">
        <span>共 <strong>{{ resultCounts.total }}</strong> 行</span>
        <el-button link @click="locateStatus('passed')">
          <el-tag type="success" effect="plain">通过 {{ resultCounts.passed }}</el-tag>
        </el-button>
        <el-button link @click="locateStatus('warning')">
          <el-tag type="warning" effect="plain">提醒 {{ resultCounts.warning }}</el-tag>
        </el-button>
        <el-button link @click="locateStatus('blocked')">
          <el-tag type="danger" effect="plain">待处理 {{ resultCounts.blocked }}</el-tag>
        </el-button>
      </div>

      <el-alert
        v-for="message in parseWarnings"
        :key="message"
        :title="message"
        type="info"
        show-icon
        :closable="false"
      />

      <div class="preview-table-wrap">
        <el-table
          ref="previewTable"
          :data="previewRows"
          border
          max-height="440"
          highlight-current-row
          class="list-table preview-table"
        >
          <el-table-column prop="source_row" label="Excel 行" width="78" fixed />
          <el-table-column label="状态" width="88" fixed>
            <template #default="{ row }">
              <el-tag :type="statusType(row.status)" effect="plain">{{ statusText(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="Product" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">{{ row.normalized.product }}</template>
          </el-table-column>
          <el-table-column label="Length" width="82">
            <template #default="{ row }">{{ row.normalized.length }}</template>
          </el-table-column>
          <el-table-column label="Color" width="86">
            <template #default="{ row }">{{ row.normalized.color }}</template>
          </el-table-column>
          <el-table-column label="Weight" width="88">
            <template #default="{ row }">{{ row.normalized.weight }}</template>
          </el-table-column>
          <el-table-column label="数量" width="70" align="right">
            <template #default="{ row }">{{ row.normalized.quantity }}</template>
          </el-table-column>
          <el-table-column label="Excel 成交价" width="118" align="right">
            <template #default="{ row }">{{ displayUnitPrice(row.normalized.unit_price) }}</template>
          </el-table-column>
          <el-table-column label="客户价" width="102" align="right">
            <template #default="{ row }">{{ nullableMoney(row.customer_price) }}</template>
          </el-table-column>
          <el-table-column label="差额" width="100" align="right">
            <template #default="{ row }">{{ nullableMoney(row.price_difference) }}</template>
          </el-table-column>
          <el-table-column label="匹配结果 / 处理" min-width="290" fixed="right">
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
        title="仍有待处理行。请选择正确的产品/SKU，或在生产单中明确确认定制产品。"
        type="error"
        show-icon
        :closable="false"
      />
    </div>

    <template #footer>
      <div class="dialog-footer">
        <el-button v-if="step === 2" @click="step = 1">返回重新粘贴</el-button>
        <span class="footer-spacer" />
        <el-button @click="visible = false">取消</el-button>
        <el-button v-if="step === 1" type="primary" :loading="loading" @click="runPreview">
          校验数据
        </el-button>
        <el-button
          v-else-if="step === 2"
          type="primary"
          :disabled="hasBlockedRows || appending"
          :loading="appending"
          @click="appendToInvoice"
        >
          加入当前发票
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { previewInvoiceImport } from '@/api/invoice'
import { hasImportedBatch, parseInvoiceClipboard } from '../composables/useInvoicePasteImport'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  customerId: { type: [String, Number], default: '' },
  customerName: { type: String, default: '' },
  orderType: { type: String, required: true },
  currency: { type: String, required: true },
  existingItems: { type: Array, default: () => [] },
})

const emit = defineEmits(['update:modelValue', 'append'])
const step = ref(1)
const pasteText = ref('')
const pasteError = ref('')
const loading = ref(false)
const appending = ref(false)
const preview = ref(null)
const previewTable = ref(null)
const parseWarnings = ref([])

const visible = computed({
  get: () => props.modelValue,
  set: value => emit('update:modelValue', value),
})
const previewRows = computed(() => preview.value?.rows || [])
const resultCounts = computed(() => previewRows.value.reduce((counts, row) => {
  counts.total += 1
  counts[row.status] += 1
  return counts
}, { total: 0, passed: 0, warning: 0, blocked: 0 }))
const hasBlockedRows = computed(() => resultCounts.value.blocked > 0)

watch(() => props.modelValue, value => {
  if (value) resetImport()
})

watch(
  () => [props.customerId, props.orderType, props.currency],
  (current, previous) => {
    if (!props.modelValue || !previous || current.every((value, index) => value === previous[index])) return
    visible.value = false
    resetImport()
    ElMessage.warning('客户、订单类型或币种已变化，请重新打开并校验导入数据')
  },
)

function resetImport() {
  step.value = 1
  pasteText.value = ''
  pasteError.value = ''
  preview.value = null
  parseWarnings.value = []
  loading.value = false
  appending.value = false
}

async function runPreview() {
  pasteError.value = ''
  let parsed
  try {
    parsed = parseInvoiceClipboard(pasteText.value)
  } catch (error) {
    pasteError.value = error.message || '无法解析粘贴内容'
    return
  }

  loading.value = true
  try {
    preview.value = await previewInvoiceImport({
      customer_id: props.customerId,
      order_type: props.orderType,
      currency: props.currency,
      rows: parsed.rows,
    })
    parseWarnings.value = parsed.warnings
    step.value = 2
  } catch (error) {
    pasteError.value = error?.message || '校验失败，请保留当前内容后重试'
  } finally {
    loading.value = false
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

function appendToInvoice() {
  if (hasBlockedRows.value || !preview.value) return
  if (hasImportedBatch(props.existingItems, preview.value.batch_fingerprint)) {
    ElMessage.warning('这批数据已经加入当前发票')
    return
  }
  appending.value = true
  emit('append', {
    rows: previewRows.value,
    fingerprint: preview.value.batch_fingerprint,
  })
  step.value = 3
  visible.value = false
  appending.value = false
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
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed.toFixed(2) : String(value || '—')
}
</script>

<style scoped>
.import-steps { margin: 0 auto 24px; max-width: 760px; }
.context-bar { display: flex; gap: 12px; margin-bottom: 20px; padding: 12px 16px; border: 1px solid var(--border-color); border-radius: 8px; background: var(--toolbar-bg); }
.context-bar span { display: flex; align-items: baseline; gap: 8px; min-width: 160px; color: var(--text-primary); }
.context-bar small { color: var(--text-tertiary); }
.paste-stage, .preview-stage { display: grid; gap: 14px; }
.stage-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.stage-heading h3 { margin: 0 0 6px; font-size: 16px; color: var(--text-primary); }
.stage-heading p { margin: 0; color: var(--text-secondary); }
.result-summary { display: flex; align-items: center; gap: 10px; }
.preview-table-wrap { overflow: hidden; border-radius: 8px; }
.resolution-cell { display: grid; gap: 6px; }
.matched-product, .custom-confirmed { color: var(--text-secondary); }
.custom-confirmed { color: var(--color-success-text); }
.row-messages { margin: 0; padding-left: 18px; color: var(--color-warning-text); font-size: 12px; line-height: 1.45; }
.row-messages .error-text { color: var(--color-danger-text); }
.dialog-footer { display: flex; align-items: center; width: 100%; }
.footer-spacer { flex: 1; }
@media (max-width: 720px) {
  .context-bar { flex-direction: column; gap: 6px; }
  .stage-heading { flex-direction: column; }
}
</style>
