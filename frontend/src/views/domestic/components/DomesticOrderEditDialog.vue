<template>
  <el-dialog :model-value="modelValue" title="编辑订单" width="860px" append-to-body destroy-on-close
    :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy" :before-close="closeOrder">
    <div v-loading="loading" class="order-edit-body">
      <template v-if="detail">
        <div class="order-edit-summary">
          <strong>{{ detail.domestic_no }}</strong>
          <span>{{ production ? `生产订单 · ${detail.customer_name || '公司备货'}` : `客户编码：${detail.customer_custom_code || '未填写'} · ${detail.order_category_label}` }}</span>
          <span>{{ detail.status_label }}</span>
        </div>
        <el-form label-position="top" :disabled="headerSaving || !editable">
          <div class="order-edit-grid">
            <el-form-item v-if="production" label="客户店名">
              <el-select v-model="header.production_customer_id" filterable clearable remote :remote-method="searchProductionCustomers" :loading="customerLoading" placeholder="选填，不选则为公司备货">
                <el-option v-for="customer in customerChoices" :key="customer.id" :value="customer.id" :label="customer.shop_name" />
              </el-select>
            </el-form-item>
            <el-form-item v-if="!production" label="客户订单号"><el-input v-model="header.order_no" placeholder="选填" maxlength="64" /></el-form-item>
            <el-form-item label="下单日期" required><el-date-picker v-model="header.order_date" type="date" value-format="YYYY-MM-DD" /></el-form-item>
            <el-form-item v-if="!production" label="要求发货日期" required><el-date-picker v-model="header.required_ship_date" type="date" value-format="YYYY-MM-DD" /></el-form-item>
            <el-form-item v-if="!production" label="订单类型" required>
              <el-select v-model="header.order_type"><el-option v-for="option in options.order_types" :key="option.value" :label="option.label" :value="option.value" /></el-select>
            </el-form-item>
            <el-form-item v-if="!production" label="订单渠道" required>
              <el-select v-model="header.order_channel"><el-option v-for="option in options.order_channels" :key="option.value" :label="option.label" :value="option.value" /></el-select>
            </el-form-item>
          </div>
          <el-form-item label="订单备注"><el-input v-model="header.remark" type="textarea" :rows="2" maxlength="1000" /></el-form-item>
        </el-form>
        <div class="order-edit-actions">
          <GlassButton v-permission="'domestic:write'" variant="primary" :loading="headerSaving" :disabled="!editable || !headerDirty" @click="saveHeader">保存订单信息</GlassButton>
        </div>
        <div class="order-edit-item-heading">
          <h3>产品明细</h3>
          <GlassButton v-if="detail.status === 0 && editable" v-permission="'domestic:write'" variant="secondary" left-icon="Plus" :disabled="busy" @click="appendVisible = true">添加明细</GlassButton>
        </div>
        <p class="order-edit-hint">每条明细独立保存。产品规格和工艺路线已锁定，数量不能少于已完成报工的件数。</p>
        <div v-for="item in detail.items" :key="item.id" class="order-edit-item">
          <div><strong>{{ item.line_code }} · {{ item.product_name }}</strong><div class="order-edit-hint">{{ item.order_qty }} 件<span v-if="!production"> · 成交单价 ¥{{ Number(item.unit_price).toFixed(2) }}</span></div></div>
          <GlassButton v-permission="'domestic:write'" variant="secondary" left-icon="EditPen" :disabled="!editable || item.status === 2" @click="openItem(item)">编辑明细</GlassButton>
        </div>
      </template>
    </div>
    <template #footer><GlassButton variant="ghost" :disabled="busy" @click="closeOrder()">关闭</GlassButton></template>
  </el-dialog>

  <el-dialog :model-value="itemDialog.visible" :title="`编辑明细 ${itemDialog.item?.line_code || ''}`" width="720px"
    append-to-body destroy-on-close :close-on-click-modal="false" :close-on-press-escape="!itemBusy" :show-close="!itemBusy" :before-close="closeItem">
    <template v-if="itemDialog.item">
      <p class="order-edit-hint">{{ itemDialog.item.product_name }}</p>
      <el-form label-position="top" :disabled="itemDialog.saving">
        <div class="order-edit-grid">
          <el-form-item label="数量" required><el-input-number v-model="itemDialog.form.order_qty" :min="1" :max="2000" :precision="0" /></el-form-item>
          <el-form-item v-if="!production" label="成交单价（含手工费）" required>
            <el-input-number v-if="Number(itemDialog.item.original_price) > 0" v-model="itemDialog.form.unit_price" :min="Number(itemDialog.item.labor_fee || 0) + 0.01"
              :max="Number(itemDialog.item.original_price || 0) + Number(itemDialog.item.labor_fee || 0)" :precision="2" :controls="false" />
            <el-input v-else :model-value="Number(itemDialog.item.unit_price || 0).toFixed(2)" disabled />
            <span v-if="!Number(itemDialog.item.original_price)" class="order-edit-hint">历史明细尚无原价，完成报价后才能改价。</span>
          </el-form-item>
        </div>
        <p v-if="!production" class="order-edit-hint">原价 ¥{{ Number(itemDialog.item.original_price).toFixed(2) }}，手工费 ¥{{ Number(itemDialog.item.labor_fee || 0).toFixed(2) }}。优惠后商品单价 ¥{{ (Number(itemDialog.form.unit_price || 0) - Number(itemDialog.item.labor_fee || 0)).toFixed(2) }}。</p>
        <div class="order-edit-grid">
          <el-form-item v-for="section in sections" :key="section.key" :label="section.label">
            <el-input v-model="itemDialog.form[section.key]" type="textarea" :rows="3" :maxlength="['hairstyle', 'color'].includes(section.key) ? 1000 : 2000" />
            <div class="order-edit-images">
              <div v-for="(path, index) in itemDialog.form[section.imageKey]" :key="`${path}-${index}`">
                <DomesticImages :paths="[path]" />
                <GlassButton variant="link" link-tone="danger" :disabled="itemBusy" @click="itemDialog.form[section.imageKey].splice(index, 1)">移除图片</GlassButton>
              </div>
            </div>
            <AppUpload v-if="!itemDialog.saving" :model-value="itemDialog.form[section.imageKey].map(path => ({ path }))"
              :upload-fn="file => uploadReference(section.imageKey, file)" :show-list="false" multiple
              accept=".jpg,.jpeg,.png,.webp" :max-size-mb="20" button-text="添加参考图" />
          </el-form-item>
        </div>
      </el-form>
      <p v-if="!production && detail.status !== 0 && amountDelta" class="order-edit-hint">
        保存后将{{ amountDelta > 0 ? '补扣' : '退回' }}客户余额 ¥{{ Math.abs(amountDelta).toFixed(2) }}。
      </p>
    </template>
    <template #footer>
      <GlassButton variant="ghost" :disabled="itemBusy" @click="closeItem()">取消</GlassButton>
      <GlassButton v-permission="'domestic:write'" variant="primary" :disabled="pendingUploads > 0 || !itemDirty" :loading="itemDialog.saving" @click="saveItem">保存这条明细</GlassButton>
    </template>
  </el-dialog>
  <DomesticDraftItemDialog v-if="appendVisible && detail" :order="detail" :options="options" @close="appendVisible = false" @saved="reloadAfterAppend" />
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { DETAIL_SECTIONS, getOptions, getOrder, listCustomers, updateOrder, updateOrderItem, uploadImage } from '@/api/domestic'
import { useAuthStore } from '@/stores/auth'
import AppUpload from '@/components/AppUpload.vue'
import GlassButton from '@/components/GlassButton.vue'
import DomesticImages from '@/components/domestic/DomesticImages.vue'
import { createLatestRequestRunner } from '../composables/latestRequest'
import DomesticDraftItemDialog from './DomesticDraftItemDialog.vue'
import { detailSectionsForKind } from '../domesticOrderKinds'
import { orderHeaderForm, buildHeaderPatch, orderItemForm, buildItemPatch, itemEditDelta, itemPriceError } from '../domesticOrderEditing'

const props = defineProps({ modelValue: Boolean, orderId: Number, initialItemId: Number })
const emit = defineEmits(['update:modelValue', 'saved'])
const auth = useAuthStore()
const detail = ref(null), loading = ref(false), headerSaving = ref(false), pendingUploads = ref(0)
const options = ref({ order_types: [], order_channels: [] })
const header = reactive(orderHeaderForm(null))
const customerOptions = ref([]), customerLoading = ref(false)
const runLatestCustomerSearch = createLatestRequestRunner()
const customerChoices = computed(() => {
  const current = detail.value?.customer_id ? [{ id: detail.value.customer_id, shop_name: detail.value.customer_name }] : []
  return [...new Map([...current, ...customerOptions.value].map(row => [row.id, row])).values()]
})
async function searchProductionCustomers(keyword) {
  customerLoading.value = true
  await runLatestCustomerSearch(
    () => listCustomers({ page: 1, page_size: 50, keyword, status: 1 }),
    res => { customerOptions.value = res.data?.items || [] },
    () => { customerLoading.value = false },
  )
}
const appendVisible = ref(false)
const itemDialog = reactive({ visible: false, item: null, form: {}, saving: false })
let loadSequence = 0
const production = computed(() => detail.value?.order_kind === 'production')
const editable = computed(() => detail.value?.created_by === auth.user?.id && ![3, 4].includes(detail.value?.status))
const sections = computed(() => detailSectionsForKind(detail.value?.order_kind, DETAIL_SECTIONS))
const headerDirty = computed(() => detail.value && Object.keys(buildHeaderPatch(detail.value, header)).length > 0)
const itemDirty = computed(() => itemDialog.item && Object.keys(buildItemPatch(detail.value, itemDialog.item, itemDialog.form)).length > 0)
const amountDelta = computed(() => itemDialog.item ? itemEditDelta(itemDialog.item, itemDialog.form) : 0)
const itemBusy = computed(() => itemDialog.saving || pendingUploads.value > 0)
const busy = computed(() => loading.value || headerSaving.value || itemBusy.value || itemDialog.visible || appendVisible.value)

watch(() => [props.modelValue, props.orderId], async ([visible, id]) => {
  const sequence = ++loadSequence
  if (!visible || !id) return
  loading.value = true
  detail.value = null
  itemDialog.visible = false
  appendVisible.value = false
  try {
    const [order, opts] = await Promise.all([getOrder(id), getOptions()])
    if (sequence !== loadSequence) return
    detail.value = order.data
    options.value = opts.data || options.value
    Object.assign(header, orderHeaderForm(detail.value))
    if (production.value) await searchProductionCustomers('')
    const item = detail.value.items.find(row => row.id === props.initialItemId)
    if (item && editable.value && item.status !== 2) openItem(item)
  } catch { /* API interceptor reports the load failure. */ } finally {
    if (sequence === loadSequence) loading.value = false
  }
}, { immediate: true })

async function canDiscard(dirty) {
  if (!dirty) return true
  try {
    await ElMessageBox.confirm('未保存的修改将丢失，确认关闭？', '放弃修改', { confirmButtonText: '放弃修改', cancelButtonText: '继续编辑' })
    return true
  } catch { return false }
}

async function closeOrder(done) {
  if (busy.value || !await canDiscard(headerDirty.value)) return
  if (typeof done === 'function') done()
  emit('update:modelValue', false)
}

async function closeItem(done) {
  if (itemBusy.value || !await canDiscard(itemDirty.value)) return
  if (typeof done === 'function') done()
  itemDialog.visible = false
}

async function reloadAfterAppend() {
  loading.value = true
  emit('saved')
  try { const res = await getOrder(detail.value.id); detail.value = res.data } catch { /* API interceptor reports refresh failure. */ } finally { loading.value = false }
}

async function saveHeader() {
  if (!editable.value || headerSaving.value) return
  if (!header.order_date || (!production.value && (!header.required_ship_date || !header.order_type || !header.order_channel))) {
    return ElMessage.warning('请补齐日期、订单类型和渠道等必填项')
  }
  const patch = buildHeaderPatch(detail.value, header)
  if (!Object.keys(patch).length) return
  headerSaving.value = true
  try {
    await updateOrder(detail.value.id, patch)
    Object.assign(detail.value, patch)
    if (Object.hasOwn(patch, 'production_customer_id')) {
      detail.value.customer_id = patch.production_customer_id
      detail.value.customer_name = customerChoices.value.find(row => row.id === patch.production_customer_id)?.shop_name || null
    }
    ElMessage.success('订单信息已保存')
    emit('saved')
  } catch { /* API interceptor reports the save failure. */ } finally { headerSaving.value = false }
}

function openItem(item) {
  if (!editable.value || item.status === 2) return
  Object.assign(itemDialog, { visible: true, item, form: orderItemForm(item), saving: false })
}

async function uploadReference(key, file) {
  const form = itemDialog.form
  pendingUploads.value += 1
  try {
    const res = await uploadImage(file)
    form[key].push(res.data.path)
    return res.data
  } finally { pendingUploads.value -= 1 }
}

async function saveItem() {
  if (!editable.value || itemBusy.value || !itemDialog.item) return
  const form = itemDialog.form, item = itemDialog.item
  if (!Number.isInteger(form.order_qty) || form.order_qty < 1) return ElMessage.warning('数量必须为正整数')
  const patch = buildItemPatch(detail.value, item, form)
  const priceError = itemPriceError(item, patch)
  if (priceError) return ElMessage.warning(priceError)
  if (!Object.keys(patch).length) return
  itemDialog.saving = true
  try {
    if (!production.value && detail.value.status !== 0 && amountDelta.value) {
      try {
        await ElMessageBox.confirm(`本次修改将${amountDelta.value > 0 ? '补扣' : '退回'}客户余额 ¥${Math.abs(amountDelta.value).toFixed(2)}，确认保存？`, '确认金额变动', { confirmButtonText: '确认保存', cancelButtonText: '继续编辑' })
      } catch { return }
    }
    await updateOrderItem(item.id, patch)
    itemDialog.visible = false
    ElMessage.success('明细已保存')
    emit('saved')
    const res = await getOrder(detail.value.id)
    detail.value = res.data
  } catch { /* API interceptor reports errors; unsaved inputs remain editable. */ } finally { itemDialog.saving = false }
}
</script>

<style scoped>
.order-edit-body { min-height: 140px; }
.order-edit-summary { display: flex; flex-wrap: wrap; gap: 8px 16px; margin-bottom: 20px; }
.order-edit-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 20px; }
.order-edit-grid :deep(.el-date-editor), .order-edit-grid :deep(.el-input-number) { width: 100%; }
.order-edit-actions { display: flex; justify-content: flex-end; margin-bottom: 24px; }
.order-edit-hint { color: var(--el-text-color-secondary); font-size: 13px; line-height: 1.6; margin: 8px 0; }
.order-edit-item-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.order-edit-item { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 14px 0; border-top: 1px solid var(--el-border-color-lighter); }
.order-edit-images { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0; }
@media (max-width: 600px) { .order-edit-grid { grid-template-columns: minmax(0, 1fr); } .order-edit-item { align-items: flex-start; flex-wrap: wrap; } }
</style>
