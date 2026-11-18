<template>
  <article class="review-line" :class="'tone-' + state.tone">
    <header>
      <input v-if="editable && !line.batch_id && status === 'matched'" type="checkbox" :checked="line.selected"
        :disabled="busy" :aria-label="'勾选第 ' + line.line_no + ' 行'" @change="$emit('change', { selected: $event.target.checked })" />
      <span class="line-index">第 {{ line.line_no }} 行</span>
      <el-tag :type="line.batch_id ? 'info' : state.tone" effect="plain" size="small">{{ line.batch_id ? '已提交批次' : state.label }}</el-tag>
      <strong v-if="line.values.quantity" class="quantity">{{ line.values.quantity }} {{ line.values.quantity_unit }}</strong>
    </header>
    <p class="raw">{{ line.raw.raw }}</p>
    <template v-if="status !== 'skipped'">
      <strong v-if="product" class="product">{{ product.name }}</strong>
      <p class="spec">{{ specs }}</p>
      <p v-if="line.match.order" class="secondary">
        {{ orderLabel(line.match.order) }}<span v-if="line.match.order.invoice_no"> · {{ line.match.order.invoice_no }}</span>
      </p>
      <p v-for="item in line.match.ignored_orders" :key="item.kind + item.ref" class="secondary">
        单号 {{ item.ref }} 对应{{ item.kind === 'stock' ? '库存单' : '预售单' }}，不做发票对应
      </p>
      <p v-if="line.match.reason" class="reason">{{ line.match.reason }}</p>
      <p v-if="line.match.excess_quantity" class="reason">超出发票数量 {{ line.match.excess_quantity }} 件</p>
      <p v-if="line.values.grade_source === 'inherited'" class="secondary">等级 {{ line.values.grade_raw }} 沿用上一行，仍需核对</p>
      <details v-if="line.raw.doubts?.length" class="secondary">
        <summary>识别疑点</summary><ul><li v-for="(doubt, index) in line.raw.doubts" :key="index">{{ doubt }}</li></ul>
      </details>
      <details v-if="line.match.references?.length" class="secondary">
        <summary>相近规格</summary><ul><li v-for="item in line.match.references" :key="item.sku_id">{{ item.name }}</li></ul>
      </details>
    </template>
    <p v-else class="secondary">{{ line.match.reason }}</p>
    <footer v-if="editable && !line.batch_id" class="line-actions">
      <label v-if="status === 'matched' && line.match.route !== 'inbound_only'" class="writeback">
        <el-switch :model-value="line.writeback_enabled" :disabled="busy" aria-label="回写或对应"
          @change="$emit('change', { writeback_enabled: $event })" /> 回写 / 对应
      </label>
      <GlassButton variant="link" :disabled="busy" @click="$emit('edit')">修正</GlassButton>
      <GlassButton v-if="status === 'blocked'" variant="link" :disabled="busy" @click="$emit('change', { refresh: true })">重新匹配</GlassButton>
      <GlassButton v-if="['choose', 'confirm', 'decide'].includes(status)" variant="primary"
        :disabled="busy" @click="$emit('choose')">{{ status === 'choose' ? '查看候选' : '核对' }}</GlassButton>
    </footer>
    <p v-if="status === 'matched'" class="secondary">{{ targetLabel(line) }}</p>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import { lineStatuses, orderLabel, targetLabel } from '../inboundLabels'

const props = defineProps({
  line: { type: Object, required: true }, editable: Boolean, busy: Boolean,
})
defineEmits(['change', 'edit', 'choose'])
const status = computed(() => props.line.match_status)
const state = computed(() => lineStatuses[status.value])
const product = computed(() => props.line.match.product)
const specs = computed(() => {
  const { values, match } = props.line
  return [values.grade_raw, values.process_raw, match.length_in ? match.length_in + '″' : null,
    product.value?.color || values.color_raw, match.weight_g ? match.weight_g + ' g' : null,
  ].filter(Boolean).join(' · ')
})
</script>

<style scoped>
.review-line {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color);
  border-left: 3px solid var(--el-border-color);
  border-radius: 12px;
  padding: 12px 14px;
  transition: border-color 150ms ease, background-color 150ms ease;
  overflow-wrap: anywhere;
}
.tone-success { border-left-color: var(--el-color-success); }
.tone-warning { border-left-color: var(--el-color-warning); }
.tone-danger { border-left-color: var(--el-color-danger); }
.tone-info { background: var(--el-fill-color-light); }
header, .line-actions, .writeback { display: flex; align-items: center; gap: 8px; }
.line-actions { flex-wrap: wrap; justify-content: flex-end; }
.writeback { margin-right: auto; }
input[type='checkbox'] { width: 20px; height: 20px; margin: 0; accent-color: var(--el-color-primary); }
.quantity { margin-left: auto; }
p { margin: 6px 0; }
.line-index, .raw, .secondary { color: var(--el-text-color-secondary); font-size: 13px; }
.reason { color: var(--el-text-color-primary); font-weight: 600; }
.spec, .product { display: block; }
@media (prefers-reduced-motion: reduce) { .review-line { transition: none; } }
</style>
