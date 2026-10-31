<template>
  <el-dialog :model-value="modelValue" :title="definition.label" width="640px" :show-close="!command.pending.value" :close-on-click-modal="!command.pending.value" :close-on-press-escape="!command.pending.value" @update:model-value="$emit('update:modelValue', $event)">
    <p>{{ item?.product_name }} · {{ item?.spec_info }} · 版本 {{ form.expected_version }}</p>
    <p>{{ definition.hint }}</p>
    <el-form label-position="top" :disabled="command.pending.value">
      <el-form-item v-if="isMaterial" label="半成品物料（必选）">
        <el-select v-model="form.material_id" filterable remote :remote-method="searchOptions" :loading="options.loading.value" placeholder="搜索物料编码 / 尺寸 / 颜色">
          <el-option v-for="entry in options.items.value" :key="entry.id" :value="entry.id" :disabled="operation === 'issue' && !entry.active" :label="`${entry.label} · 可用 ${entry.available_grams} 克${entry.active ? '' : '（停用）'}`" />
          <template #footer><GlassButton v-if="options.hasMore.value" variant="link" :loading="options.loading.value" @click="options.load(optionScope)">加载更多物料</GlassButton></template>
        </el-select>
      </el-form-item>
      <el-form-item v-if="operation === 'supplies'" label="供货销售明细（必选）">
        <el-select v-model="form.invoice_item_id" filterable remote :remote-method="searchOptions" :loading="options.loading.value" placeholder="搜索有权限的同 SKU 订单号">
          <el-option v-for="entry in options.items.value" :key="entry.invoice_item_id" :value="entry.invoice_item_id" :label="`${entry.invoice_no} · 明细 ${entry.invoice_item_id} · 剩余需求 ${entry.remaining_quantity} 件`" />
          <template #footer><GlassButton v-if="options.hasMore.value" variant="link" :loading="options.loading.value" @click="options.load(optionScope)">加载更多订单</GlassButton></template>
        </el-select>
      </el-form-item>
      <ListPageStatus v-if="isMaterial || operation === 'supplies'" :error="options.errorMessage.value" :loading="false" :has-data="options.hasData.value" :paged="false" @retry="options.load(optionScope)" />
      <el-form-item v-if="isMaterial" label="本次克数（必填，最多三位小数）"><el-input v-model="form.quantity_grams" inputmode="decimal" placeholder="例如 125.500" /></el-form-item>
      <el-form-item v-else-if="!['terminate', 'reverse'].includes(operation)" label="本次件数（必填）"><el-input-number v-model="form.quantity" :min="1" :max="2147483647" :precision="0" /></el-form-item>
      <template v-if="operation === 'receive'">
        <el-form-item label="验收仓库（必选）"><el-select v-model="form.warehouse_id" filterable><el-option v-for="entry in reference.data.value?.warehouses || []" :key="entry.id" :value="entry.id" :label="entry.name" /></el-select></el-form-item>
        <el-form-item label="质量状态"><el-select v-model="form.quality"><el-option v-for="(label, value) in qualityLabels" :key="value" :value="value" :label="label" /></el-select></el-form-item>
        <template v-if="pendingSupplies.length && form.quality === 'sellable'">
          <p>本次合格件数中分配给销售的数量（剩余部分计入公共库存）</p>
          <el-form-item v-for="entry in pendingSupplies" :key="entry.id" :label="`供货关系 ${entry.id} · 销售明细 ${entry.invoice_item_id} · 尚待交付 ${entry.remaining} 件`"><el-input-number v-model="form.allocations[entry.id]" :min="0" :max="entry.remaining" :precision="0" /></el-form-item>
        </template>
        <ListPageStatus :error="reference.errorMessage.value" :loading="false" :has-data="reference.hasData.value" :paged="false" @retry="reference.load()" />
      </template>
      <p v-if="operation === 'reverse'">原验收：{{ receipt?.warehouse_name }} · {{ receipt?.quantity }} 件 · {{ qualityLabels[receipt?.quality] }}</p>
      <el-form-item label="操作原因（必填）"><el-input v-model="form.reason" type="textarea" maxlength="500" /></el-form-item>
    </el-form>
    <el-alert v-if="command.failure.value" :title="command.failure.value" type="error" :closable="false" show-icon />
    <p v-if="command.failure.value">输入及原请求已保留。响应丢失时重试原请求；版本冲突须先核对历史凭证和最新数据。</p>
    <GlassButton v-if="command.failure.value" :disabled="command.pending.value" @click="restart">核对后重新开始</GlassButton>
    <template #footer><div class="dialog-footer"><GlassButton :disabled="command.pending.value" @click="$emit('update:modelValue', false)">返回</GlassButton><GlassButton v-permission="definition.permission" :variant="['reverse', 'terminate', 'loss'].includes(operation) ? 'danger' : 'primary'" :loading="command.pending.value" @click="submit">{{ definition.label }}</GlassButton></div></template>
  </el-dialog>
</template>
<script setup>
import { computed, ref, shallowRef, watch } from 'vue'
import { getNativeProductionReference, getNativeSupplyOptions, getNativeMaterialOptions, actNativeProductionItem, releaseNativeProductionSupply, reverseNativeProductionReceipt } from '@/api/nativeProduction'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { useCursorResource } from '@/composables/useCursorResource'
import { useNativeCommand } from '@/views/finance/native/useNativeCommand'
import { confirmDanger, msgSuccess } from '@/utils/feedback'
import { productionActions, qualityLabels } from './labels'
const props = defineProps({ modelValue: Boolean, item: Object, operation: String, supplies: Array, supply: Object, receipt: Object })
const emit = defineEmits(['update:modelValue', 'saved'])
const commandState = shallowRef(useNativeCommand()), drafts = new Map(), form = ref({}), optionScope = ref({})
const command = { pending: computed(() => commandState.value.pending.value), failure: computed(() => commandState.value.failure.value) }
const targetKey = () => `${props.item.id}:${props.operation}:${props.supply?.id || ''}:${props.receipt?.event_id || ''}`
const definition = computed(() => productionActions[props.operation] || productionActions.complete)
const isMaterial = computed(() => ['issue', 'return', 'loss'].includes(props.operation))
const availableSupplies = computed(() => (props.supplies || []).filter(row => row.production_item_id === props.item?.id)
  .map(row => ({ ...row, remaining: row.quantity - row.received_quantity - row.released_quantity })).filter(row => row.remaining > 0))
const pendingSupplies = ref([])
const reference = useAsyncResource(async (_, { signal }) => (await getNativeProductionReference({ signal, suppressToast: true })).data)
const options = useCursorResource(async (scope, page, { signal }) => {
  const fetcher = scope.kind === 'material' ? getNativeMaterialOptions : getNativeSupplyOptions
  const { data } = await fetcher({ item_id: scope.item_id, keyword: scope.keyword, page, page_size: 50 }, { signal, suppressToast: true })
  return { items: data.items, nextCursor: page + 1, hasMore: page * 50 < data.total }
}, { initialCursor: 1, key: row => row.invoice_item_id || row.id })
function searchOptions(keyword = '') {
  optionScope.value = { item_id: props.item.id, kind: isMaterial.value ? 'material' : 'supply', keyword }
  options.clear(); options.load(optionScope.value)
}
function restoreDraft() {
  const key = targetKey(), kept = drafts.get(key)
  if (kept) { form.value = kept.form; commandState.value = kept.command; pendingSupplies.value = kept.supplies; return }
  pendingSupplies.value = availableSupplies.value
  form.value = { expected_version: props.item.local_version, reason: '', quantity: 1, quantity_grams: '', material_id: null,
    invoice_item_id: null, warehouse_id: null, quality: 'sellable', allocations: Object.fromEntries(pendingSupplies.value.map(row => [row.id, 0])) }
  commandState.value = useNativeCommand()
  drafts.set(key, { form: form.value, command: commandState.value, supplies: pendingSupplies.value })
}
watch(() => props.modelValue, visible => {
  if (!visible) { options.clear(); return }
  restoreDraft()
  if (props.operation === 'receive') reference.load()
  if (isMaterial.value || props.operation === 'supplies') searchOptions()
})
async function restart() {
  await confirmDanger('重新开始生产操作', props.item.product_name, '请先核对历史凭证及刷新后的数量，确认原操作是否成功。重新开始会使用新的请求及当前读取版本。')
  drafts.delete(targetKey()); restoreDraft()
}
async function submit() {
  const target = { key: targetKey(), item_id: props.item.id, operation: props.operation, supply_id: props.supply?.id,
    event_id: props.receipt?.event_id, label: definition.value.label, hint: definition.value.hint, product: props.item.product_name }
  const inputs = form.value, material = isMaterial.value, supplies = pendingSupplies.value, activeCommand = commandState.value
  const result = await activeCommand.run({ payload: () => {
    const body = { expected_version: inputs.expected_version, reason: inputs.reason.trim() }
    if (!body.reason) throw new Error('请填写操作原因')
    if (material) {
      if (!inputs.material_id || !/^\d+(\.\d{1,3})?$/.test(inputs.quantity_grams) || !Number(inputs.quantity_grams)) throw new Error('请选择物料并填写大于零、最多三位小数的克数')
      return { ...body, material_id: inputs.material_id, quantity_grams: inputs.quantity_grams }
    }
    if (['terminate', 'reverse'].includes(target.operation)) return body
    if (!Number.isInteger(inputs.quantity) || inputs.quantity <= 0) throw new Error('请填写正整数件数')
    body.quantity = inputs.quantity
    if (target.operation === 'supplies') { if (!inputs.invoice_item_id) throw new Error('请选择销售明细'); body.invoice_item_id = inputs.invoice_item_id }
    if (target.operation === 'receive') {
      if (!inputs.warehouse_id) throw new Error('请选择验收仓库')
      body.warehouse_id = inputs.warehouse_id; body.quality = inputs.quality
      body.allocations = body.quality === 'sellable' ? supplies.filter(row => inputs.allocations[row.id] > 0).map(row => ({ supply_id: row.id, quantity: inputs.allocations[row.id] })) : []
      if (body.allocations.some(row => !Number.isInteger(row.quantity)) || body.allocations.reduce((sum, row) => sum + row.quantity, 0) > body.quantity) throw new Error('销售分配须为整数且合计不能超过本次验收件数')
    }
    return body
  }, confirm: ['reverse', 'terminate', 'loss'].includes(target.operation) ? () => confirmDanger(target.label, target.product, target.hint) : undefined,
  send: body => target.operation === 'release' ? releaseNativeProductionSupply(target.supply_id, body)
    : target.operation === 'reverse' ? reverseNativeProductionReceipt(target.event_id, body)
      : actNativeProductionItem(target.item_id, material ? `materials/${target.operation}` : target.operation, body) })
  if (result.ok) { drafts.delete(target.key); msgSuccess(target.label); if (target.key === targetKey()) emit('update:modelValue', false); emit('saved', result.data) }
}
</script>
<style scoped>.el-select { width: 100%; }</style>
