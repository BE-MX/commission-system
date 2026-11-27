<script setup>
import { computed, nextTick, ref, onBeforeUnmount, watch } from 'vue'
import { portalAdminApi } from '@/api/portal'
import { useAuthStore } from '@/stores/auth'
import PortalProductFilters from './PortalProductFilters.vue'
const props = defineProps({ access: Object, section: String })
const emit = defineEmits(['close', 'changed'])
const auth = useAuthStore(), data = ref(null), delivery = ref({}), rows = ref([]), selected = ref([]), batch = ref(''), busy = ref(false), uncertain = ref(false), error = ref('')
const emptyFilters = () => ({ color: '', length: '', weight: '', grade: '', color_type: '' })
const filters = ref(emptyFilters())
const invalidPrice = ref(null)
const filtering = computed(() => Object.values(filters.value).some(value => String(value ?? '').trim()))
// 克重输入 20 与 20g 视为同一规格
const normWeight = value => String(value ?? '').trim().toLowerCase().replace(/\s+/g, '').replace(/g$/, '')
const visibleRows = computed(() => {
  const { color, length, weight, grade, color_type: colorType } = filters.value
  const colorTerm = color.trim().toLowerCase(), lengthTerm = length.trim(), weightTerm = normWeight(weight)
  return rows.value.filter(row => (!colorTerm || String(row.color_name ?? '').toLowerCase().includes(colorTerm))
    && (!lengthTerm || String(row.length ?? '').trim() === lengthTerm)
    && (!weightTerm || normWeight(row.weight) === weightTerm)
    && (!grade || row.grade === grade)
    && (!colorType || row.color_type === colorType))
})
const visibleSelectedCount = computed(() => visibleRows.value.filter(row => selected.value.includes(row.id)).length)
function selectVisible(checked) {
  const ids = new Set(selected.value)
  for (const row of visibleRows.value) checked ? ids.add(row.id) : ids.delete(row.id)
  selected.value = [...ids]
}
const fields = [['contact_name', '联系人'], ['phone', '联系电话'], ['address_line1', '地址'], ['address_line2', '补充地址'], ['city', '城市'], ['region', '州 / 省'], ['postal_code', '邮编'], ['country_code', '国家代码（US / GB）']]
let live = true, generation = 0, controller = new AbortController()
watch(() => auth.accessToken, () => { live = false; controller.abort(); emit('close') })
onBeforeUnmount(() => { live = false; controller.abort() })
async function load() {
  const current = ++generation, id = props.access.id, section = props.section
  controller.abort(); controller = new AbortController()
  busy.value = true; error.value = ''; invalidPrice.value = null; data.value = null; delivery.value = {}; rows.value = []; selected.value = []; batch.value = ''; filters.value = emptyFilters()
  try {
    const result = await portalAdminApi.customerSettings(id, section, controller.signal)
    if (!live || current !== generation) return
    data.value = result; delivery.value = { ...Object.fromEntries(fields.map(([key]) => [key, ''])), ...result.delivery }
    rows.value = (result.items || []).map(row => ({ ...row, price: row.unit_price ?? row.standard_price ?? '', changed: false }))
    selected.value = []; uncertain.value = false
  } catch (e) { if (live && current === generation) { data.value = null; error.value = e?.response?.data?.message || '读取失败，请重试。' } }
  finally { if (live && current === generation) busy.value = false }
}
function markPriceChanged(row) {
  row.changed = true
  if (invalidPrice.value?.id === row.id) {
    invalidPrice.value = null
    error.value = ''
  }
}
function applyBatch() {
  const ids = new Set(selected.value)
  for (const row of rows.value) {
    if (ids.has(row.id)) {
      row.price = batch.value
      markPriceChanged(row)
    }
  }
}
function parsePrice(raw) {
  if (raw === '') return { value: null }
  const text = String(raw).trim().replace(/[０-９．]/g, char => char.normalize('NFKC'))
  if (/^-\d+(?:\.\d+)?$/.test(text)) return { reason: '单价须大于 0。' }
  if (!/^\d+(?:\.\d+)?$/.test(text)) return { reason: '请用数字和小数点填写，例如 48.29。' }
  const [whole, fraction = ''] = text.replace(/^0+(?=\d)/, '').split('.')
  if (whole.length > 8) return { reason: '单价的整数部分最多 8 位。' }
  if (fraction.length > 4) return { reason: '单价最多保留 4 位小数。' }
  if (!/[1-9]/.test(whole + fraction)) return { reason: '单价须大于 0。' }
  return { value: `${whole}.${fraction.padEnd(4, '0')}` }
}
async function showPriceError(row, reason) {
  if (!visibleRows.value.includes(row)) filters.value = emptyFilters()
  invalidPrice.value = { id: row.id, reason }
  const spec = [row.model_name, row.color_name, row.length && `长度 ${row.length}`, row.weight, row.sale_unit].filter(Boolean).join(' · ')
  const entered = String(row.price).trim() ? `「${row.price}」` : '（只有空格）'
  error.value = `${spec} 的客户单价${entered}有误。${reason}`
  await nextTick()
  document.getElementById(`customer-unit-price-${row.id}`)?.focus()
}
async function save() {
  if (busy.value || uncertain.value || !data.value) return
  error.value = ''
  let body
  if (props.section === 'prices') {
    const items = []
    for (const row of rows.value.filter(row => row.changed)) {
      const { value, reason } = parsePrice(row.price)
      if (reason) return showPriceError(row, reason)
      items.push({ item_id: row.id, unit_price: value })
    }
    if (!items.length) { error.value = '请先修改商品单价。'; return }
    body = { items }
  } else {
    body = { delivery: { ...delivery.value, country_code: delivery.value.country_code.toUpperCase() } }
  }
  const current = generation, id = props.access.id, section = props.section, version = data.value.row_version
  busy.value = true
  try {
    await portalAdminApi.saveCustomerSettings(id, section, body, version)
    if (live && current === generation) { emit('changed', props.section === 'delivery' ? '客户地址已保存' : '客户商品价格已保存，旧报价已失效'); emit('close') }
  } catch (e) {
    if (live && current === generation) { uncertain.value = !e.response || e.response.status >= 500; error.value = uncertain.value ? '保存结果未确认，请读取当前资料核对后再编辑。' : e.response?.data?.message || '保存失败。' }
  } finally { if (live && current === generation) busy.value = false }
}
watch(() => [props.access.id, props.section], () => { uncertain.value = false; load() }, { immediate: true })
</script>
<template>
  <el-dialog :model-value="true" class="portal-customer-settings" :title="`${section === 'delivery' ? '客户地址' : '商品价格'} · ${access.company_display_name}`" width="760px" :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy" @close="emit('close')">
    <el-alert v-if="error" :title="error" type="error" :closable="false" role="alert" />
    <div v-loading="busy">
      <el-form v-if="data && section === 'delivery'" label-position="top" :disabled="busy || uncertain">
        <el-form-item v-for="[key, label] in fields" :key="key" :label="label"><el-input v-model="delivery[key]" :maxlength="key === 'country_code' ? 2 : key === 'phone' ? 40 : key === 'postal_code' ? 32 : key.startsWith('address') ? 200 : 100" :aria-label="label" /></el-form-item>
      </el-form>
      <template v-if="data && section === 'prices'">
        <div class="batch-price"><el-input v-model="batch" aria-label="批量单价" placeholder="USD 单价" :disabled="busy || uncertain" /><GlassButton :disabled="!selected.length || busy || uncertain" @click="applyBatch">应用到所选 {{ selected.length }} 项</GlassButton></div>
        <p>未设置专属价时显示标准价供填写；清空单价可恢复现有客户定价规则。</p>
        <PortalProductFilters class="price-filters" :filters="filters" :facets="data.facets" />
        <p v-if="selected.length && filtering">已选 {{ selected.length }} 项，其中当前结果可见 {{ visibleSelectedCount }} 项。</p>
        <el-table :data="visibleRows" border class="list-table" v-sticky-scrollbar max-height="440">
          <el-table-column min-width="55"><template #header><el-checkbox class="price-select" :model-value="visibleRows.length > 0 && visibleSelectedCount === visibleRows.length" :indeterminate="visibleSelectedCount > 0 && visibleSelectedCount < visibleRows.length" :disabled="busy || uncertain || !visibleRows.length" aria-label="选择当前筛选结果" @change="selectVisible" /></template><template #default="{ row }"><el-checkbox v-model="selected" class="price-select" :value="row.id" :disabled="busy || uncertain" :aria-label="`选择 ${row.model_name} ${row.color_name} ${row.length} ${row.weight ?? ''} ${row.sale_unit ?? ''}`"><span aria-hidden="true"></span></el-checkbox></template></el-table-column>
          <el-table-column label="商品" min-width="260"><template #default="{ row }"><div class="product-name">{{ row.model_name }}</div><div class="product-spec">{{ row.color_name }} · 长度 {{ row.length ?? '—' }}<template v-if="row.weight"> · {{ row.weight }}</template><template v-if="row.sale_unit"> · {{ row.sale_unit }}</template></div></template></el-table-column>
          <el-table-column prop="standard_price" label="标准价 USD" min-width="135" />
          <el-table-column label="客户单价 USD" min-width="170">
            <template #default="{ row }">
              <el-input :id="`customer-unit-price-${row.id}`" v-model="row.price" inputmode="decimal"
                :aria-label="`${row.model_name} ${row.color_name} ${row.length} ${row.weight ?? ''} ${row.sale_unit ?? ''} 客户单价`"
                :aria-invalid="invalidPrice?.id === row.id || undefined" :aria-describedby="invalidPrice?.id === row.id ? 'customer-price-error' : undefined"
                :disabled="busy || uncertain" @input="markPriceChanged(row)" />
              <span v-if="invalidPrice?.id === row.id" id="customer-price-error" class="price-error">{{ invalidPrice.reason }}</span>
            </template>
          </el-table-column>
        </el-table>
      </template>
    </div>
    <template #footer><GlassButton :disabled="busy" @click="emit('close')">关闭</GlassButton><GlassButton :disabled="busy" @click="load">读取当前资料</GlassButton><GlassButton v-permission="'portal_access:admin'" variant="primary" :disabled="busy || uncertain || !data" @click="save">保存</GlassButton></template>
  </el-dialog>
</template>
<style scoped>
.batch-price { display: flex; gap: 12px; margin: 16px 0; }
.batch-price .el-input { max-width: 180px; }
.price-filters { margin-bottom: 12px; }
.product-name, .product-spec { white-space: normal; overflow-wrap: anywhere; }
.product-spec { color: var(--text-secondary); }
.price-error { color: var(--el-color-danger); }
.price-select { margin-right: 0; }
p { color: var(--text-secondary); }
</style>

<style>
.portal-customer-settings { max-width: calc(100vw - 24px); }
.portal-customer-settings .el-dialog__footer { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
.portal-customer-settings .el-dialog__footer button { margin-left: 0; }
</style>
