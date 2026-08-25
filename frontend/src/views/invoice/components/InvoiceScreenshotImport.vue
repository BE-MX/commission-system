<template>
  <el-dialog
    v-model="visible"
    title="AI 识别 OKKI 订单截图"
    width="min(1120px, 94vw)"
    destroy-on-close
    class="screenshot-import-dialog"
  >
    <div v-if="!preview" class="upload-stage" tabindex="0" @paste="onPaste">
      <el-alert
        title="截图只作为订单数据识别，不会保存原图；识别后仍需确认再创建。"
        type="info"
        :closable="false"
        show-icon
      />
      <div class="order-type-row">
        <span>创建类型</span>
        <el-radio-group v-model="orderType">
          <el-radio-button value="stock">库存单</el-radio-button>
          <el-radio-button value="production">生产单</el-radio-button>
        </el-radio-group>
      </div>
      <el-upload
        drag
        :auto-upload="false"
        :show-file-list="false"
        accept="image/png,image/jpeg,image/webp"
        :on-change="onFileChange"
      >
        <el-icon class="upload-icon"><Picture /></el-icon>
        <div class="el-upload__text">拖入 OKKI 订单截图，或点击选择图片</div>
        <template #tip>
          <div class="el-upload__tip">支持 PNG、JPG、WebP，最大 10MB；请包含客户、订单金额和完整产品表格。</div>
        </template>
      </el-upload>
      <div class="clipboard-row">
        <el-button @click="readClipboard"><el-icon><DocumentCopy /></el-icon>从剪贴板读取图片</el-button>
        <span>也可以先点击此区域，再直接按 Ctrl/Cmd + V</span>
      </div>
      <div v-if="imagePreviewUrl" class="image-preview">
        <img :src="imagePreviewUrl" alt="待识别 OKKI 订单截图" />
        <span>{{ imageFile?.name }}</span>
      </div>
    </div>

    <div v-else class="preview-stage">
      <div class="preview-heading">
        <div>
          <h3>{{ preview.extraction.order_name || '未识别订单名称' }}</h3>
          <p>
            {{ preview.extraction.order_date || '日期未知' }} ·
            {{ preview.extraction.currency || '币种未知' }}
            {{ preview.extraction.order_amount ?? '金额未知' }}
          </p>
        </div>
        <el-tag :type="preview.ready ? 'success' : 'warning'" effect="plain">
          {{ preview.ready ? '可以填入发票' : '需要处理' }}
        </el-tag>
      </div>

      <div class="match-grid">
        <div class="match-card">
          <span>客户匹配</span>
          <el-select v-model="customerId" filterable placeholder="请选择客户" @change="rerunResolve">
            <el-option
              v-for="item in preview.customer_match.candidates"
              :key="item.company_id"
              :label="`${item.company_name}${item.country_name ? `（${item.country_name}）` : ''}`"
              :value="String(item.company_id)"
            />
          </el-select>
          <small>截图：{{ preview.extraction.customer_name || '—' }}</small>
        </div>
        <div class="match-card">
          <span>业务员匹配</span>
          <el-select v-model="salesUserId" filterable placeholder="请选择业务员" @change="rerunResolve">
            <el-option
              v-for="item in preview.sales_match.candidates"
              :key="item.id"
              :label="`${item.real_name}（${item.username}）`"
              :value="item.id"
            />
          </el-select>
          <small>截图：{{ preview.extraction.salesperson_name || '—' }} · {{ preview.extraction.department_name || '部门未知' }}</small>
        </div>
        <div class="match-card">
          <span>OKKI 来源订单</span>
          <strong v-if="preview.source_order.status === 'matched'">
            {{ preview.source_order.order_no || preview.source_order.order_id }}
          </strong>
          <strong v-else>{{ sourceStatusText }}</strong>
          <small>导入后会禁止再次同步 OKKI，防止重复建单</small>
        </div>
      </div>

      <div class="totals-bar">
        <span>识别产品合计 <strong>{{ money(preview.totals.recognized_product_amount) }}</strong></span>
        <span>明细计算合计 <strong>{{ money(preview.totals.calculated_product_amount) }}</strong></span>
        <span>订单金额 <strong>{{ preview.extraction.currency || 'USD' }} {{ money(preview.totals.recognized_order_amount) }}</strong></span>
        <span>差额 <strong>{{ money(preview.totals.difference) }}</strong></span>
      </div>

      <div class="line-table-wrap">
        <el-table :data="preview.import_preview?.rows || []" border class="list-table">
          <el-table-column prop="source_row" label="#" min-width="48" max-width="60" />
          <el-table-column label="截图产品" min-width="220" max-width="340" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="product-source">
                <strong>{{ row.normalized.product }}</strong>
                <small>{{ row.normalized.product_no || '无产品编号' }} · {{ row.normalized.length }} · {{ row.normalized.color }} · {{ row.normalized.weight }}</small>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="数量" min-width="68" max-width="88">
            <template #default="{ row }">{{ row.normalized.quantity }}</template>
          </el-table-column>
          <el-table-column label="单价" min-width="86" max-width="110">
            <template #default="{ row }">{{ money4(row.normalized.unit_price) }}</template>
          </el-table-column>
          <el-table-column label="系统产品匹配" min-width="260" max-width="380">
            <template #default="{ row }">
              <div class="resolution-cell">
                <el-select
                  v-if="row.candidates?.length"
                  v-model="productSelections[row.source_row]"
                  placeholder="选择正确产品/SKU"
                  :disabled="Boolean(customRows[row.source_row])"
                  @change="rerunResolve"
                >
                  <el-option
                    v-for="candidate in row.candidates"
                    :key="candidateKey(candidate)"
                    :label="candidateLabel(candidate)"
                    :value="candidateKey(candidate)"
                    :disabled="!candidate.sku_id"
                  />
                </el-select>
                <div v-else-if="row.matched_product" class="matched-product">
                  {{ row.matched_product.product_name }} · SKU {{ row.matched_product.sku_id }}
                </div>
                <span v-else>待匹配</span>
                <el-checkbox
                  v-if="orderType === 'production' && row.can_create_custom"
                  v-model="customRows[row.source_row]"
                  @change="rerunResolve"
                >作为定制产品</el-checkbox>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="状态" min-width="86" max-width="110">
            <template #default="{ row }">
              <el-tag :type="statusType(row.status)" effect="plain">{{ statusText(row.status) }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <el-alert
        v-if="preview.blockers.length"
        title="以下问题必须处理后才能创建"
        type="error"
        :closable="false"
        show-icon
      >
        <ul><li v-for="message in preview.blockers" :key="message">{{ message }}</li></ul>
      </el-alert>
      <el-alert
        v-if="preview.warnings.length"
        title="请在保存前确认"
        type="warning"
        :closable="false"
        show-icon
      >
        <ul><li v-for="message in preview.warnings" :key="message">{{ message }}</li></ul>
      </el-alert>
    </div>

    <template #footer>
      <div class="dialog-footer">
        <el-button v-if="preview" @click="resetPreview">重新选择截图</el-button>
        <span />
        <el-button @click="visible = false">取消</el-button>
        <el-button
          v-if="!preview"
          type="primary"
          :loading="recognizing"
          :disabled="!imageFile"
          @click="recognize"
        >{{ recognizing ? '识别中' : '开始识别' }}</el-button>
        <el-button
          v-else
          type="primary"
          :disabled="!preview.ready || resolving"
          :loading="resolving"
          @click="applyPreview"
        >填入发票编辑器</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { DocumentCopy, Picture } from '@element-plus/icons-vue'
import { previewInvoiceScreenshot, resolveInvoiceScreenshot } from '@/api/invoice'

const props = defineProps({ modelValue: { type: Boolean, default: false } })
const emit = defineEmits(['update:modelValue', 'apply'])
const visible = computed({
  get: () => props.modelValue,
  set: value => emit('update:modelValue', value),
})
const orderType = ref('stock')
const imageFile = ref(null)
const imagePreviewUrl = ref('')
const recognizing = ref(false)
const resolving = ref(false)
const preview = ref(null)
const customerId = ref('')
const salesUserId = ref(null)
const productSelections = reactive({})
const customRows = reactive({})

const sourceStatusText = computed(() => ({
  missing: '暂未同步到业务库', ambiguous: '匹配到多张订单',
})[preview.value?.source_order?.status] || '未匹配')

watch(() => props.modelValue, open => { if (open) resetAll() })

function setImage(file) {
  if (!file?.type?.startsWith('image/')) {
    ElMessage.warning('请选择 PNG、JPG 或 WebP 图片')
    return
  }
  if (file.size > 10 * 1024 * 1024) {
    ElMessage.warning('截图不能超过 10MB')
    return
  }
  if (imagePreviewUrl.value) URL.revokeObjectURL(imagePreviewUrl.value)
  imageFile.value = file
  imagePreviewUrl.value = URL.createObjectURL(file)
}

function onFileChange(uploadFile) { setImage(uploadFile.raw) }

function onPaste(event) {
  const file = [...(event.clipboardData?.files || [])].find(item => item.type.startsWith('image/'))
  if (file) setImage(file)
}

async function readClipboard() {
  if (!navigator.clipboard?.read) {
    ElMessage.info('当前浏览器不支持直接读取图片，请使用 Ctrl/Cmd + V')
    return
  }
  try {
    const items = await navigator.clipboard.read()
    for (const item of items) {
      const type = item.types.find(value => value.startsWith('image/'))
      if (!type) continue
      const blob = await item.getType(type)
      setImage(new File([blob], 'okki-screenshot.png', { type }))
      return
    }
    ElMessage.info('剪贴板中没有图片')
  } catch {
    ElMessage.warning('无法读取剪贴板，请允许权限或使用 Ctrl/Cmd + V')
  }
}

async function recognize() {
  if (!imageFile.value) return
  recognizing.value = true
  try {
    const formData = new FormData()
    formData.append('image', imageFile.value)
    applyResponse(await previewInvoiceScreenshot(formData, orderType.value))
  } finally {
    recognizing.value = false
  }
}

async function rerunResolve() {
  if (!preview.value || resolving.value) return
  resolving.value = true
  try {
    const selections = Object.entries(productSelections)
      .filter(([, value]) => value)
      .map(([sourceRow, value]) => {
        const [productId, skuId] = value.split(':').map(Number)
        return { source_row: Number(sourceRow), product_id: productId, sku_id: skuId }
      })
    applyResponse(await resolveInvoiceScreenshot({
      extraction: preview.value.extraction,
      source_image_sha256: preview.value.source_image_sha256,
      order_type: orderType.value,
      customer_id: customerId.value || null,
      sales_user_id: salesUserId.value || null,
      product_selections: selections,
      custom_rows: Object.entries(customRows).filter(([, value]) => value).map(([key]) => Number(key)),
    }))
  } finally {
    resolving.value = false
  }
}

function applyResponse(value) {
  preview.value = value
  customerId.value = value.customer_match.selected?.company_id
    ? String(value.customer_match.selected.company_id) : customerId.value
  salesUserId.value = value.sales_match.selected?.id || salesUserId.value
  for (const row of value.import_preview?.rows || []) {
    if (row.matched_product?.sku_id && !productSelections[row.source_row]) {
      productSelections[row.source_row] = candidateKey(row.matched_product)
    }
  }
}

function applyPreview() {
  if (!preview.value?.ready) return
  emit('apply', preview.value)
  visible.value = false
}

function resetPreview() {
  preview.value = null
  customerId.value = ''
  salesUserId.value = null
  Object.keys(productSelections).forEach(key => delete productSelections[key])
  Object.keys(customRows).forEach(key => delete customRows[key])
}

function resetAll() {
  resetPreview()
  orderType.value = 'stock'
  imageFile.value = null
  if (imagePreviewUrl.value) URL.revokeObjectURL(imagePreviewUrl.value)
  imagePreviewUrl.value = ''
  recognizing.value = false
  resolving.value = false
}

const candidateKey = candidate => `${candidate.product_id}:${candidate.sku_id || ''}`
const candidateLabel = candidate => `${candidate.product_name} · SKU ${candidate.sku_id || '不可用'}`
const statusType = status => ({ passed: 'success', warning: 'warning', blocked: 'danger' })[status] || 'info'
const statusText = status => ({ passed: '通过', warning: '提醒', blocked: '待处理' })[status] || status
const money = value => value == null ? '—' : Number(value).toFixed(2)
const money4 = value => value == null ? '—' : Number(value).toFixed(4)
onUnmounted(() => { if (imagePreviewUrl.value) URL.revokeObjectURL(imagePreviewUrl.value) })
</script>

<style scoped>
.upload-stage, .preview-stage { display: grid; gap: 16px; }
.order-type-row, .clipboard-row, .preview-heading, .totals-bar, .dialog-footer { display: flex; align-items: center; gap: 12px; }
.order-type-row { justify-content: space-between; }
.upload-icon { font-size: 42px; color: var(--color-primary); }
.clipboard-row { justify-content: center; color: var(--text-secondary); font-size: 12px; }
.image-preview { display: grid; justify-items: center; gap: 8px; color: var(--text-secondary); font-size: 12px; }
.image-preview img { max-width: 100%; max-height: 260px; border: 1px solid var(--border-color); border-radius: 8px; object-fit: contain; }
.preview-heading { justify-content: space-between; }
.preview-heading h3 { margin: 0 0 4px; color: var(--text-primary); font-size: 16px; }
.preview-heading p { margin: 0; color: var(--text-secondary); }
.match-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.match-card { display: grid; gap: 7px; padding: 12px; border: 1px solid var(--border-color); border-radius: 10px; background: var(--toolbar-bg); }
.match-card > span, .match-card small { color: var(--text-secondary); font-size: 12px; }
.totals-bar { flex-wrap: wrap; padding: 10px 12px; border-radius: 8px; background: var(--table-header-bg); color: var(--text-secondary); }
.totals-bar strong { color: var(--text-primary); font-variant-numeric: tabular-nums; }
.line-table-wrap { overflow-x: auto; border: 1px solid var(--border-color); border-radius: 10px; }
.product-source, .resolution-cell { display: grid; gap: 5px; }
.product-source small { color: var(--text-secondary); }
.matched-product { color: var(--text-secondary); }
.preview-stage ul { margin: 4px 0 0; padding-left: 20px; }
.dialog-footer { width: 100%; }
.dialog-footer > span { flex: 1; }
@media (max-width: 860px) { .match-grid { grid-template-columns: 1fr; } .clipboard-row { align-items: flex-start; flex-direction: column; } }
</style>
