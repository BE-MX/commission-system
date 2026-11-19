<template>
  <el-drawer :model-value="Boolean(line)" title="核对匹配" direction="btt" size="640px" class="factory-candidate-sheet"
    append-to-body @close="$emit('close')">
    <div v-if="line" class="options">
      <p class="sheet-raw"><span>第 {{ line.line_no }} 行原单</span>{{ line.raw.raw }}</p>
      <p v-if="line.match.reason" class="sheet-reason">{{ line.match.reason }}</p>
      <template v-if="orderChoices.length">
        <button v-for="order in orderChoices" :key="order.kind + order.id" class="option" type="button"
          :disabled="busy || order.restricted" @click="$emit('select', { order: { kind: order.kind, id: order.id } })">
          <strong>{{ orderLabel(order) }}</strong>
          <span>{{ order.date }} · {{ order.line_count }} 行 · {{ order.quantity }} 件</span>
          <span v-if="order.invoice_no">{{ order.invoice_no }}</span>
          <span v-if="order.restricted" class="option-note">需有发票查看权限</span>
          <span v-else-if="order.reason" class="option-note">{{ order.reason }}</span>
        </button>
      </template>
      <template v-else-if="line.match_status === 'decide'">
        <button v-if="line.match.allowed_routes?.includes('inbound_only')" class="option" type="button" :disabled="busy"
          @click="$emit('select', { route: 'inbound_only' })"><strong>只入库</strong><span>不回写任何生产单</span></button>
        <button v-if="line.match.allowed_routes?.includes('cross')" class="option" type="button" :disabled="busy"
          @click="$emit('select', { route: 'cross' })"><strong>改为跨生产备货单分配</strong><span>按回写时的可用余量分配</span></button>
        <button class="option" type="button" :disabled="busy" @click="$emit('edit')"><strong>更正单号</strong><span>原单号识别错了，手工改正</span></button>
      </template>
      <template v-else>
        <button v-for="row in line.match.candidates" :key="row.product_id + ':' + row.sku_id" class="option"
          :class="{ recommended: row.quantity_match && !row.issue }" type="button"
          :disabled="busy || Boolean(row.issue)" @click="pick(row)">
          <span class="option-head"><strong>{{ row.name }}</strong><span v-if="row.quantity_match" class="match-badge">数量吻合</span></span>
          <span>{{ row.size }} · {{ row.color }} · {{ row.weight }} · SKU {{ row.sku_id ?? '待绑定' }}</span>
          <span v-if="row.ordered != null">下单 {{ row.ordered }} 件 · {{ line.match.order?.kind === 'invoice' ? '可对应' : '未入库' }} {{ row.remaining }} 件</span>
          <span v-if="row.issue" class="option-note">{{ row.issue }}</span>
        </button>
        <label v-if="hasConversion" class="check-row"><input v-model="suggest" type="checkbox" />将核对后的颜色写法提交词表</label>
      </template>
    </div>
  </el-drawer>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { orderLabel } from '../inboundLabels'

const props = defineProps({ line: Object, busy: Boolean })
const emit = defineEmits(['close', 'select', 'edit'])
const suggest = ref(false)
const orderChoices = computed(() => {
  const line = props.line
  if (!line || line.match_status !== 'choose' || line.match.order || line.match.candidates.length) return []
  return line.match.orders
})
function colorKey(value) {
  return String(value ?? '').normalize('NFKC').replace(/\s|^#|#$/g, '').toUpperCase()
}
const converted = row => colorKey(props.line?.values.color_raw) !== colorKey(row.color)
const hasConversion = computed(() => props.line?.match.candidates.some(row => !row.issue && converted(row)))
function pick(row) {
  emit('select', { sku_id: row.sku_id, suggest_color_alias: suggest.value && converted(row) })
}
watch(() => props.line?.id, () => { suggest.value = false })
</script>

<style scoped>
.options { max-width: 640px; margin-inline: auto; display: grid; gap: 10px; padding-bottom: env(safe-area-inset-bottom); }
.check-row { display: flex; align-items: center; gap: 10px; min-height: 44px; font-size: 14px; cursor: pointer; }
.check-row input { width: 22px; height: 22px; margin: 0; flex-shrink: 0; accent-color: var(--button-primary); cursor: pointer; }
.check-row input:focus-visible { outline: 3px solid var(--button-focus, var(--button-primary)); outline-offset: 2px; }
.sheet-raw {
  display: flex; gap: 8px; margin: 0; padding: 10px 12px; border-radius: 10px; background: var(--page-bg);
  font-family: var(--font-mono, ui-monospace, monospace); font-size: 12px; color: var(--text-secondary); overflow-wrap: anywhere;
}
.sheet-raw span { flex-shrink: 0; font-family: var(--font-body, system-ui, sans-serif); font-weight: 650; }
.sheet-reason { margin: 0 0 4px; padding: 10px 12px; border-radius: 10px; background: var(--color-warning-bg); color: var(--color-warning-text); font-size: 14px; font-weight: 650; }
.option {
  display: grid; gap: 4px; width: 100%; min-height: 56px; padding: 14px 16px; border: 1px solid var(--border-color); border-radius: 14px;
  background: var(--card-bg); color: var(--text-primary); font: inherit; font-size: 13px; text-align: left; cursor: pointer; overflow-wrap: anywhere;
  transition: transform 140ms cubic-bezier(.23, 1, .32, 1), border-color 160ms ease;
}
.option strong { font-size: 15px; }
.option > span { color: var(--text-secondary); }
.option.recommended { border-color: var(--color-success); background: color-mix(in srgb, var(--color-success-bg) 55%, var(--card-bg)); }
.option-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
.match-badge { flex-shrink: 0; padding: 2px 8px; border-radius: 999px; background: var(--color-success-bg); color: var(--color-success-text); font-size: 12px; font-weight: 650; }
.option-note { color: var(--color-warning-text) !important; font-weight: 600; }
.option:active:not(:disabled) { transform: scale(.98); }
.option:disabled { background: var(--button-disabled-bg); color: var(--button-disabled-text); cursor: not-allowed; }
.option:focus-visible { outline: 3px solid var(--button-focus, var(--button-primary)); outline-offset: 2px; }
@media (hover: hover) and (pointer: fine) { .option:hover:not(:disabled) { border-color: var(--button-primary-hover); } }
@media (prefers-reduced-motion: reduce) { .option { transition: none; } .option:active { transform: none; } }
</style>

<style>
.factory-candidate-sheet.el-drawer { max-height: 82dvh; border-radius: 20px 20px 0 0; }
.factory-candidate-sheet.el-drawer.btt {
  transition-property: transform, opacity;
  transition-timing-function: cubic-bezier(0.32, 0.72, 0, 1);
  transition-duration: 240ms;
}
.el-drawer-fade-leave-active .factory-candidate-sheet.el-drawer.btt { transition-duration: 180ms; }
@media (prefers-reduced-motion: reduce) {
  .factory-candidate-sheet.el-drawer.btt { transition-property: opacity; transform: none; }
}
</style>
