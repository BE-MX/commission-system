<template>
  <el-drawer :model-value="Boolean(line)" title="核对匹配" direction="btt" size="640px" class="factory-candidate-sheet"
    append-to-body @close="$emit('close')">
    <div v-if="line" class="options">
      <p v-if="line.match.reason">{{ line.match.reason }}</p>
      <template v-if="orderChoices.length">
        <GlassButton v-for="order in orderChoices" :key="order.kind + order.id"
          :disabled="busy || order.restricted" @click="$emit('select', { order: { kind: order.kind, id: order.id } })">
          <span class="option">
            <strong>{{ orderLabel(order) }}</strong>
            <span>{{ order.date }} · {{ order.line_count }} 行 · {{ order.quantity }} 件</span>
            <span v-if="order.invoice_no">{{ order.invoice_no }}</span>
            <span v-if="order.restricted">需有发票查看权限</span>
            <span v-else-if="order.reason">{{ order.reason }}</span>
          </span>
        </GlassButton>
      </template>
      <template v-else-if="line.match_status === 'decide'">
        <GlassButton v-if="line.match.allowed_routes?.includes('inbound_only')" :disabled="busy" @click="$emit('select', { route: 'inbound_only' })">只入库</GlassButton>
        <GlassButton v-if="line.match.allowed_routes?.includes('cross')" :disabled="busy" @click="$emit('select', { route: 'cross' })">改为跨生产备货单分配</GlassButton>
        <GlassButton :disabled="busy" @click="$emit('edit')">更正单号</GlassButton>
      </template>
      <template v-else>
        <GlassButton v-for="row in line.match.candidates" :key="row.product_id + ':' + row.sku_id"
          :disabled="busy || Boolean(row.issue)" @click="pick(row)">
          <span class="option">
            <strong>{{ row.name }}</strong>
            <span>{{ row.size }} · {{ row.color }} · {{ row.weight }} · SKU {{ row.sku_id ?? '待绑定' }}</span>
            <span v-if="row.ordered != null">下单 {{ row.ordered }} 件 · {{ line.match.order?.kind === 'invoice' ? '可对应' : '未入库' }} {{ row.remaining }} 件</span>
            <span v-if="row.quantity_match">数量吻合</span>
            <span v-if="row.issue">{{ row.issue }}</span>
          </span>
        </GlassButton>
        <el-checkbox v-if="hasConversion" v-model="suggest">将核对后的颜色写法提交词表</el-checkbox>
      </template>
    </div>
  </el-drawer>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
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
.options { max-width: 700px; margin-inline: auto; display: grid; gap: 10px; }
.options p { margin: 0 0 6px; }
.options :deep(.glass-button) { width: 100%; min-height: 44px; text-align: left; height: auto; white-space: normal; }
.option { display: grid; gap: 3px; padding: 6px; text-align: left; }
.option span { font-size: 13px; }
</style>

<style>
.factory-candidate-sheet.el-drawer { max-height: 82dvh; border-radius: 16px 16px 0 0; }
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
