<template>
  <el-dialog model-value title="添加明细" width="760px" top="16px" append-to-body destroy-on-close
    :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy" :before-close="close">
    <p class="draft-item-hint">添加到 {{ order.domestic_no }}，保存后仍为草稿，提交订单时统一结算。</p>
    <el-form label-position="top" :disabled="saving">
      <div class="draft-item-grid">
        <el-form-item label="产品类型" required>
          <el-select v-model="item.attrs.product_type" @change="changeType">
            <el-option v-for="type in options.product_types" :key="type.value" :label="type.label" :value="type.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="数量" required><el-input-number v-model="item.order_qty" :min="1" :max="2000" :precision="0" /></el-form-item>
        <el-form-item v-for="field in fields" :key="field" :label="attributeFieldLabel(item.attrs.product_type, field)" :required="requiredFields.includes(field)">
          <el-select v-model="item.attrs[field]" filterable clearable :allow-create="special" :default-first-option="special">
            <el-option v-for="value in attributeOptions(options, order.order_category, item.attrs.product_type, field)" :key="value" :label="value" :value="value" />
          </el-select>
        </el-form-item>
      </div>
      <p class="draft-item-hint">工艺路线：{{ route?.route_name || '选择规格后自动匹配' }}</p>
      <template v-if="!production">
        <div v-if="special" class="draft-item-grid">
          <el-form-item label="销售价" required><el-input-number v-model="item.specialPrice" :min="0.01" :precision="2" :controls="false" /></el-form-item>
        </div>
        <template v-else>
          <p class="draft-item-hint">{{ quoteStatusLabel(item.quoteStatus) }}<template v-if="item.quoteStatus === 'priced'"> · 原始价 ¥{{ Number(item.quote.original_price).toFixed(2) }}</template></p>
          <GlassButton v-if="item.quoteStatus !== 'priced'" variant="link" :disabled="saving || quoteLoading" @click="refreshQuote">重新报价</GlassButton>
          <div class="draft-item-grid">
            <el-form-item label="优惠价" required>
              <el-input-number v-if="item.quoteStatus === 'priced'" :model-value="effectiveDiscountPrice(item)" :min="Number(item.quote.original_price) > 0 ? 0.01 : 0" :max="Number(item.quote.original_price)" :precision="2" :controls="false" @change="value => item.manualDiscountPrice = value" />
              <el-input v-else model-value="完成规格后自动报价" disabled />
            </el-form-item>
            <el-form-item label="手工费"><el-input-number v-model="item.laborFee" :min="0" :precision="2" :controls="false" /></el-form-item>
          </div>
        </template>
      </template>
      <el-form-item v-for="section in sections" :key="section.key" :label="section.label">
        <el-input v-model="item[section.key]" type="textarea" :rows="2" :maxlength="['hairstyle', 'color'].includes(section.key) ? 1000 : 2000" />
        <div class="draft-item-images">
          <div v-for="(file, index) in item[section.imageKey]" :key="`${file.path}-${index}`">
            <DomesticImages :paths="[file.path]" />
            <GlassButton variant="link" link-tone="danger" :disabled="busy" @click="item[section.imageKey].splice(index, 1)">移除图片</GlassButton>
          </div>
        </div>
        <AppUpload :model-value="item[section.imageKey]" :upload-fn="file => uploadReference(section.imageKey, file)" :disabled="saving" :show-list="false" multiple
          accept=".jpg,.jpeg,.png,.webp" :max-size-mb="20" button-text="添加参考图" />
      </el-form-item>
    </el-form>
    <template #footer>
      <GlassButton variant="ghost" :disabled="busy" @click="close">取消</GlassButton>
      <GlassButton v-permission="'domestic:write'" variant="primary" :loading="saving" :disabled="pendingUploads > 0 || quoteLoading" @click="save">保存新增明细</GlassButton>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { addDraftOrderItem, DETAIL_SECTIONS, quoteDomesticPrices, uploadImage } from '@/api/domestic'
import GlassButton from '@/components/GlassButton.vue'
import AppUpload from '@/components/AppUpload.vue'
import DomesticImages from '@/components/domestic/DomesticImages.vue'
import { attributeFieldLabel, attributeOptions, normalizeItemAttrs, requiredAttributeFields, validateItemAttributes, visibleAttributeFields } from '../domesticAttributeRules'
import { buildProductionPayload, detailSectionsForKind, routeForOrder } from '../domesticOrderKinds'
import { applyQuoteChange, applyQuoteResult, buildCreateItems, buildQuoteRequest, effectiveDiscountPrice, ensureRequestIdentity, invalidateItemQuote, quoteChangedDetail, quoteStatusLabel } from '../composables/domesticMemberPricing'

const props = defineProps({ order: { type: Object, required: true }, options: { type: Object, required: true } })
const emit = defineEmits(['close', 'saved'])
const makeRequestId = () => globalThis.crypto?.randomUUID?.() || `draft-item-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`
const item = reactive({ key: makeRequestId(), attrs: { product_type: 'cap' }, order_qty: 1,
  quoteStatus: 'pending', quote: null, expectedQuote: null, manualDiscountPrice: null, laborFee: 0, specialPrice: null,
  hairstyle: '', hairstyle_images: [], color: '', color_images: [], style_requirement: '', style_images: [], remark: '', remark_images: [] })
const saving = ref(false), pendingUploads = ref(0), quoteLoading = ref(false)
const busy = computed(() => saving.value || pendingUploads.value > 0)
const production = computed(() => props.order.order_kind === 'production')
const special = computed(() => !production.value && props.order.order_category === 'special')
const fields = computed(() => visibleAttributeFields(item.attrs, props.order.order_kind))
const requiredFields = computed(() => requiredAttributeFields(item.attrs, props.order.order_kind))
const sections = computed(() => detailSectionsForKind(props.order.order_kind, DETAIL_SECTIONS))
const route = computed(() => routeForOrder(item, props.order.order_kind, props.order.order_category, props.options.order_routes))
const normalize = attrs => normalizeItemAttrs(attrs, props.order.order_kind)
const form = () => ({ customer_id: props.order.customer_id, items: [item] })
const content = () => production.value ? buildProductionPayload(form()).items[0] : buildCreateItems([item], normalize)[0]
const initialContent = JSON.stringify(content())
let requestIdentity = null, quoteSequence = 0, quoteTimer

function changeType() { item.attrs = { product_type: item.attrs.product_type } }
watch(() => JSON.stringify(normalize(item.attrs)), () => {
  clearTimeout(quoteTimer)
  quoteSequence += 1
  quoteLoading.value = false
  invalidateItemQuote(item)
  if (!production.value && !special.value) quoteTimer = setTimeout(refreshQuote, 250)
})

async function refreshQuote() {
  if (production.value || special.value || validateItemAttributes({ ...item.attrs }, props.order.order_kind)) return
  const sequence = ++quoteSequence
  quoteLoading.value = true
  item.quoteStatus = 'quoting'
  try {
    const res = await quoteDomesticPrices(buildQuoteRequest(form(), normalize))
    if (sequence === quoteSequence) applyQuoteResult([item], res.data)
  } catch { if (sequence === quoteSequence) item.quoteStatus = 'pending' } finally {
    if (sequence === quoteSequence) quoteLoading.value = false
  }
}
onBeforeUnmount(() => { clearTimeout(quoteTimer); quoteSequence += 1 })

async function uploadReference(key, file) {
  pendingUploads.value += 1
  try { const res = await uploadImage(file); item[key].push(res.data); return res.data } finally { pendingUploads.value -= 1 }
}
async function close() {
  if (busy.value) return
  if (JSON.stringify(content()) !== initialContent) {
    try { await ElMessageBox.confirm('新增明细尚未保存，确认放弃？', '放弃新增明细', { confirmButtonText: '放弃修改', cancelButtonText: '继续编辑' }) } catch { return }
  }
  emit('close')
}
async function save() {
  if (busy.value || quoteLoading.value) return
  const error = validateItemAttributes({ ...item.attrs }, props.order.order_kind)
  if (error) return ElMessage.warning(error)
  if (!Number.isInteger(item.order_qty) || item.order_qty < 1) return ElMessage.warning('数量必须为正整数')
  if (special.value && !(item.specialPrice > 0)) return ElMessage.warning('请填写销售价')
  if (!production.value && !special.value && !item.expectedQuote) return ElMessage.warning('请先完成报价')
  const payload = content()
  requestIdentity = ensureRequestIdentity(requestIdentity, payload, () => makeRequestId())
  saving.value = true
  try {
    const res = await addDraftOrderItem(props.order.id, { ...payload, request_id: requestIdentity.requestId })
    if (res.data.warning) ElMessage.warning(res.data.warning)
    else ElMessage.success('明细已添加')
    emit('saved')
    emit('close')
  } catch (error) {
    const changed = quoteChangedDetail(error)
    if (changed) {
      applyQuoteChange([item], changed.current_expected_quotes, () => makeRequestId())
      ElMessage.warning('报价已变化，请核对最新价格后重新保存')
    }
  } finally { saving.value = false }
}
</script>

<style scoped>
.draft-item-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 20px; }
.draft-item-grid :deep(.el-input-number), .draft-item-grid :deep(.el-select) { width: 100%; }
.draft-item-hint { color: var(--el-text-color-secondary); font-size: 13px; line-height: 1.6; }
.draft-item-images { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0; }
@media (max-width: 600px) { .draft-item-grid { grid-template-columns: minmax(0, 1fr); } }
</style>
