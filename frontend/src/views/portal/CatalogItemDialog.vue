<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { portalAdminApi } from '@/api/portal'
import { msgError, msgSuccess } from '@/utils/feedback'
import { createAccessMutation } from './customerAccess.mjs'
import { catalogConfiguration, sourceIdentity, catalogStates } from './catalogConfiguration.mjs'
const props = defineProps({ itemId: { type: String, default: null } }), emit = defineEmits(['close', 'changed'])
const auth = useAuthStore(), current = ref(null), preview = ref(null), error = ref(''), loading = ref(false), state = ref('idle'), confirmed = ref(false)
const source = reactive({ product_id: '', sku_id: '', product_kind: 'hair' })
const form = reactive({ display_name: '', color_name: '', inventory_unit: '', sale_unit: '', conversion_factor: '', safety_buffer: '', min_qty: null, step_qty: null, status: 'draft', reason: '' })
const labels = { display_name: '标准型号显示名', color_name: '标准颜色显示名', inventory_unit: '库存数量单位', sale_unit: '销售单位', conversion_factor: '每销售单位消耗的库存数量', safety_buffer: '库存安全余量' }
const locked = computed(() => loading.value || ['sending', 'uncertain'].includes(state.value))
const isImport = computed(() => !props.itemId || !!preview.value)
const snapshot = computed(() => preview.value?.source.standard_json || current.value?.standard_json)
let generation = 0, sequence = 0, controller, frozen = null
const mutation = createAccessMutation(async operation => {
  const result = await portalAdminApi.catalogMutation(operation)
  const identity = operation.identity
  if (!result?.id || result.product_id !== identity.product_id || result.sku_id !== identity.sku_id || result.product_kind !== identity.product_kind || (operation.action === 'update' && result.id !== operation.id) || (operation.action === 'import' && result.status !== 'draft')) throw new Error('商品回执与当前操作不符，请查询当前记录。')
  return { ...result, id: operation.id }
})
const message = e => e?.response?.data?.message || e.message || '商品操作失败。'
function clearConfiguration() { for (const key of Object.keys(labels)) form[key] = ''; form.min_qty = null; form.step_qty = null; form.reason = ''; confirmed.value = false }
watch(source, () => { if (!props.itemId) { sequence++; controller?.abort(); preview.value = null; clearConfiguration() } }, { deep: true, flush: 'sync' })
watch(form, () => { confirmed.value = false }, { deep: true, flush: 'sync' })
function apply(item) { for (const key of Object.keys(labels)) form[key] = String(item[key]); form.min_qty = item.min_qty; form.step_qty = item.step_qty; form.status = item.status; form.reason = ''; confirmed.value = false }
function clear() { generation++; sequence++; controller?.abort(); mutation.clear(); current.value = null; preview.value = null; frozen = null; clearConfiguration(); state.value = 'idle'; loading.value = false }
function scopeFailure(e) { if ([401, 403, 404].includes(e?.response?.status)) { clear(); emit('changed', '当前商品访问范围已变化，已清除草稿；不能据此确认此前写入结果。'); emit('close'); return true } return false }
async function readItem() {
  const identity = generation, request = ++sequence; loading.value = true; controller?.abort(); controller = new AbortController()
  try { const result = await portalAdminApi.catalogItem(props.itemId, controller.signal); if (identity !== generation || request !== sequence) return; current.value = result; Object.assign(source, sourceIdentity(result)); apply(result) }
  catch (e) { if (identity === generation && request === sequence && !scopeFailure(e)) error.value = message(e) }
  finally { if (identity === generation && request === sequence) loading.value = false }
}
async function inspect() {
  if (locked.value) return
  let identityFields
  try { identityFields = sourceIdentity(source) } catch (e) { error.value = message(e); return }
  const identity = generation, request = ++sequence; controller?.abort(); controller = new AbortController(); loading.value = true; error.value = ''; preview.value = null; confirmed.value = false
  try {
    const result = await portalAdminApi.catalogSource(identityFields, controller.signal)
    if (identity !== generation || request !== sequence) return
    if (result.source.product_id !== identityFields.product_id || result.source.sku_id !== identityFields.sku_id || result.source.product_kind !== identityFields.product_kind || (props.itemId && result.existing_item?.id !== props.itemId)) throw new Error('来源预览与所选商品不符。')
    preview.value = result
    clearConfiguration()
    // Names are suggestions from the standard source; no unit conversion is guessed.
    form.display_name = result.source.standard_json.model; form.color_name = result.source.standard_json.color
  } catch (e) { if (identity === generation && request === sequence && !scopeFailure(e)) error.value = message(e) }
  finally { if (identity === generation && request === sequence) loading.value = false }
}
async function save() {
  if (locked.value || !confirmed.value || (!preview.value && !current.value)) return
  let operation
  try {
    const identity = sourceIdentity(source), config = catalogConfiguration(form)
    operation = isImport.value ? { action: 'import', id: `${identity.product_id}:${identity.sku_id}`, identity, version: preview.value.expected_version, body: { ...config, ...identity, standard_fingerprint: preview.value.source.standard_fingerprint } } : { action: 'update', id: props.itemId, identity, version: current.value.row_version, body: { ...config, status: form.status } }
  } catch (e) { error.value = message(e); return }
  frozen = structuredClone(operation); const identity = generation
  try {
    const promise = mutation.execute(operation); state.value = mutation.state; error.value = ''
    const result = await promise
    if (identity !== generation || !result) return
    state.value = mutation.state; msgSuccess('保存商品')
    emit('changed', `${operation.action === 'import' ? '已导入草稿，尚未发布。' : '商品配置已保存。'}影响客户 ${result.affected_customers} 个，失效报价 ${result.expired_quotes} 份。历史订单保持原样。`); emit('close')
  } catch (e) { if (identity === generation) { state.value = mutation.state; error.value = message(e) } }
}
async function recover() {
  if (loading.value || state.value !== 'uncertain' || !frozen) return
  const identity = generation; loading.value = true; error.value = ''; controller?.abort(); controller = new AbortController()
  try {
    const result = frozen.action === 'import' ? await portalAdminApi.catalogImportStatus(frozen.identity, controller.signal) : { found: true, item: await portalAdminApi.catalogItem(frozen.id, controller.signal) }
    if (identity !== generation) return
    if (!result.found) { error.value = '尚未找到导入记录，不能据此判断原请求未执行。请稍后再次查询。'; return }
    if (result.item?.product_id !== frozen.identity.product_id || result.item?.sku_id !== frozen.identity.sku_id) throw new Error('查询结果与原商品不符。')
    mutation.clear(); state.value = 'idle'; emit('changed', '已查询到当前商品，不能据此确认原写入成功。请从列表重新打开核对；本次未重发写入。'); emit('close')
  } catch (e) { if (identity === generation && !scopeFailure(e)) error.value = message(e) }
  finally { if (identity === generation) loading.value = false }
}
function close() { if (!locked.value) emit('close') }
function beforeUnload(e) { if (locked.value) { e.preventDefault(); e.returnValue = '' } }
watch(() => [auth.accessToken, auth.user], () => { clear(); emit('close') })
window.addEventListener('beforeunload', beforeUnload)
onBeforeRouteLeave(() => { if (locked.value) { msgError('请先核对商品写入结果。'); return false } })
onBeforeUnmount(() => { clear(); window.removeEventListener('beforeunload', beforeUnload) })
onMounted(() => { if (props.itemId) readItem() })
</script>

<template>
  <el-dialog :model-value="true" :title="itemId ? '管理门户商品' : '导入标准 SKU'" width="900px" class="portal-catalog-item" :close-on-click-modal="false" :close-on-press-escape="!locked" :show-close="!locked" @update:model-value="value => { if (!value) close() }">
    <div v-loading="loading"><el-alert v-if="error" :title="error" type="error" :closable="false" /><el-alert v-if="state === 'uncertain'" title="写入结果未知，原商品和配置已冻结。仅查询当前记录，不重发写入。" type="warning" :closable="false" />
      <el-form label-position="top" :disabled="locked">
        <div class="fields"><el-form-item label="方舟产品 ID"><el-input v-model="source.product_id" aria-label="方舟产品 ID" :disabled="locked || !!itemId" maxlength="19" /></el-form-item><el-form-item label="方舟 SKU ID"><el-input v-model="source.sku_id" aria-label="方舟 SKU ID" :disabled="locked || !!itemId" maxlength="19" /></el-form-item><el-form-item label="商品类别"><el-select v-model="source.product_kind" aria-label="商品类别" :disabled="locked || !!itemId"><el-option label="发制品" value="hair" /><el-option label="配件" value="accessory" /></el-select></el-form-item></div>
        <GlassButton :disabled="locked || (!!itemId && !current)" @click="inspect">{{ itemId ? '重新预览来源并准备导入草稿' : '预览标准来源' }}</GlassButton>
        <template v-if="snapshot"><div class="standard"><strong>方舟标准来源</strong><p>{{ snapshot.product_name }} · {{ snapshot.model }} / {{ snapshot.color }}</p><p>长度 {{ snapshot.length }} · 标准重量/报价单位 {{ snapshot.weight }}（不能据此推断库存单位）</p></div>
          <el-alert v-if="preview" :title="preview.existing_item ? '该 SKU 已导入。本次重新导入会改为草稿、撤下当前发布内容并使相关报价失效。请重新填写并核对换算配置。' : '仅导入为草稿，不自动发布，也不自动授予客户。'" type="warning" :closable="false" />
          <div class="fields"><el-form-item v-for="(label, key) in labels" :key="key" :label="label"><el-input v-model="form[key]" :aria-label="label" :maxlength="key.endsWith('unit') ? 32 : 128" /></el-form-item><el-form-item label="起订量（销售单位）"><el-input-number v-model="form.min_qty" aria-label="起订量" :min="1" :max="10000" :precision="0" /></el-form-item><el-form-item label="下单步长（销售单位）"><el-input-number v-model="form.step_qty" aria-label="下单步长" :min="1" :max="10000" :precision="0" /></el-form-item></div>
          <p>换算关系：1 {{ form.sale_unit || '销售单位' }} = {{ form.conversion_factor || '?' }} {{ form.inventory_unit || '库存单位' }}。安全余量按库存单位填写；请依据已确认业务口径配置。</p>
          <el-form-item v-if="!isImport" label="保存后的商品状态"><el-radio-group v-model="form.status"><el-radio-button v-for="(label, value) in catalogStates" :key="value" :value="value">{{ label }}</el-radio-button></el-radio-group></el-form-item>
          <el-alert v-if="!isImport && form.status === 'published'" title="发布会重新验证标准来源和客户映射；只向已授予此商品的客户开放，旧报价失效。" type="info" :closable="false" />
          <el-form-item label="操作原因"><el-input v-model="form.reason" aria-label="商品操作原因" maxlength="500" type="textarea" :rows="2" /></el-form-item><el-checkbox v-model="confirmed">我已核对标准来源、单位换算、起订规则及发布或撤下的影响</el-checkbox>
        </template>
      </el-form>
    </div>
    <template #footer><GlassButton :disabled="locked" @click="close">关闭</GlassButton><GlassButton v-if="state === 'uncertain'" :disabled="loading" @click="recover">查询原商品当前记录</GlassButton><GlassButton v-else v-permission="'portal_site:admin'" :disabled="locked || !confirmed || (!current && !preview)" variant="primary" @click="save">{{ isImport ? '确认导入草稿' : '保存商品配置' }}</GlassButton></template>
  </el-dialog>
</template>

<style scoped>
.fields { display: grid; grid-template-columns: 1fr 1fr; gap: 0 20px; }
.el-select, .el-input-number { width: 100%; } .el-alert, .standard { margin: 16px 0; }
p { color: var(--text-secondary); overflow-wrap: anywhere; line-height: 1.6; }
.el-checkbox { height: auto; white-space: normal; } :deep(.el-checkbox__label) { white-space: normal; line-height: 1.6; }
@media (max-width: 600px) { .fields { grid-template-columns: 1fr; } }
</style>
<style>.portal-catalog-item { max-width: calc(100vw - 24px); } .portal-catalog-item .el-dialog__footer { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; } .portal-catalog-item .el-dialog__footer button { margin-left: 0; }</style>
