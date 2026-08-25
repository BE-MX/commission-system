<template>
  <el-dialog v-model="visible" title="生产下单" width="520px" align-center>
    <div v-if="row" class="production-dialog-content">
      <div v-for="item in summary" :key="item.label" class="prod-info-row">
        <span class="prod-label">{{ item.label }}</span>
        <span class="prod-value" :class="item.className">{{ item.value }}</span>
      </div>
      <el-divider />
      <el-form :model="form" label-width="100px">
        <el-form-item label="生产下单数量" required>
          <el-input-number v-model="form.order_qty" :min="1" :max="999999" :step="1" controls-position="right" @change="onQtyChange" />
        </el-form-item>
        <el-form-item label-width="0">
          <el-checkbox v-model="form.semifinished_enabled" :disabled="loading" @change="toggleSemifinished">同步下单半成品熟料</el-checkbox>
        </el-form-item>
        <el-alert v-if="error" :title="error" type="warning" :closable="false" show-icon class="plan-alert" />
        <div v-if="form.semifinished_enabled && form.semifinished_items.length" class="semifinished-plan">
          <div v-for="item in form.semifinished_items" :key="item.material_id" class="semifinished-plan__row">
            <div><strong>{{ item.size }}/{{ item.color_code }}</strong><small>可用 {{ item.available_grams }}g</small></div>
            <el-input-number v-model="item.quantity_grams" :min="0.001" :precision="3" :step="10" />
            <span>g</span>
          </div>
        </div>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" placeholder="可选" maxlength="500" show-word-limit />
        </el-form-item>
      </el-form>
    </div>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">确认加入购物车</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { quoteSemifinished } from '@/api/semifinished'

const visible = defineModel({ type: Boolean, default: false })
const props = defineProps({ row: { type: Object, default: null }, addToCart: { type: Function, required: true } })
const form = reactive({ order_qty: 1, remark: '', semifinished_enabled: false, semifinished_items: [] })
const loading = ref(false)
const error = ref('')
const submitting = ref(false)
let quoteTimer = null
let quoteSerial = 0

const suggestedQty = computed(() => Math.max(0,
  (props.row?.safety_stock || 0) * 2 - (props.row?.enable_count || 0) - (props.row?.production_in_transit || 0),
))
const summary = computed(() => props.row ? [
  { label: '产品名称', value: props.row.product_name },
  { label: '型号', value: props.row.model },
  { label: '近30日销量', value: `${props.row.sales_30d || 0} 件` },
  { label: '生产在途', value: `${props.row.production_in_transit || 0} 件`, className: props.row.production_in_transit > 0 ? 'in-transit-active' : '' },
  { label: '当前库存', value: `${Math.round(props.row.enable_count || 0)} 件` },
  { label: '安全库存', value: `${props.row.safety_stock || 0} 件` },
  { label: '差值', value: suggestedQty.value, className: suggestedQty.value > 0 ? 'value-danger' : '' },
] : [])

watch(visible, opened => {
  if (!opened) {
    if (quoteTimer) clearTimeout(quoteTimer)
    quoteSerial += 1
    return
  }
  if (!props.row) return
  Object.assign(form, { order_qty: suggestedQty.value || 1, remark: '', semifinished_enabled: false, semifinished_items: [] })
  error.value = ''
})

async function loadQuote() {
  if (!visible.value || !props.row || !form.semifinished_enabled) return
  const serial = ++quoteSerial
  loading.value = true
  error.value = ''
  try {
    const quote = await quoteSemifinished({ product_id: props.row.product_id, finished_qty: form.order_qty })
    if (serial === quoteSerial) {
      form.semifinished_items = (quote.items || []).map(item => ({ ...item, quantity_grams: Number(item.suggested_qty_grams) }))
    }
  } catch (caught) {
    if (serial === quoteSerial) {
      form.semifinished_items = []
      error.value = caught?.response?.data?.detail || caught.message || '半成品关联加载失败'
    }
  } finally {
    if (serial === quoteSerial) loading.value = false
  }
}
function toggleSemifinished(enabled) {
  if (enabled) loadQuote()
  else { form.semifinished_items = []; error.value = '' }
}
function onQtyChange() {
  if (!form.semifinished_enabled) return
  if (quoteTimer) clearTimeout(quoteTimer)
  quoteTimer = setTimeout(loadQuote, 250)
}
function parseSpec(name) {
  const parts = (name || '').split('/')
  return `${parts[0] || ''}/${parts[1] || ''}/${parts.slice(2, -1).join('/')}/${parts.at(-1) || ''}`
}
async function submit() {
  if (!props.row) return
  if (form.semifinished_enabled && !form.semifinished_items.length) return ElMessage.warning(error.value || '未取得可下单的半成品计划')
  submitting.value = true
  try {
    const ok = await props.addToCart({
      product_id: props.row.product_id, product_name: props.row.product_name, model: props.row.model,
      spec_info: parseSpec(props.row.product_name), order_qty: form.order_qty, remark: form.remark,
      semifinished_items: form.semifinished_enabled
        ? form.semifinished_items.map(item => ({ material_id: item.material_id, quantity_grams: item.quantity_grams })) : [],
    })
    if (ok) visible.value = false
  } finally { submitting.value = false }
}
</script>

<style scoped>
.plan-alert { margin-bottom: 12px; }
.semifinished-plan { display: flex; flex-direction: column; gap: 10px; margin: 0 0 14px 100px; }
.semifinished-plan__row { display: grid; grid-template-columns: minmax(160px, 1fr) 150px 24px; align-items: center; gap: 10px; }
.semifinished-plan__row div { display: flex; flex-direction: column; }
.semifinished-plan__row small { color: var(--text-muted); }
.prod-info-row { display: flex; padding: 8px 0; border-bottom: 1px solid var(--border-color); }
.prod-label { width: 100px; color: var(--text-secondary); }
.prod-value { flex: 1; font-weight: 500; }
.in-transit-active { color: var(--color-success); font-weight: 600; }
.value-danger { color: var(--color-danger); font-weight: 600; }
</style>
