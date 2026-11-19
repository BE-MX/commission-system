<template>
  <article class="review-line" :class="['tone-' + tone, { submitted: line.batch_id }]">
    <header class="line-top">
      <span class="line-index">{{ String(line.line_no).padStart(2, '0') }}</span>
      <span class="pill" :class="'tone-' + tone">{{ line.batch_id ? '已提交批次' : state.label }}</span>
      <span v-if="line.values.quantity" class="line-qty"><b>{{ line.values.quantity }}</b> {{ line.values.quantity_unit }}</span>
    </header>

    <template v-if="status !== 'skipped'">
      <h3 class="line-product" :class="{ pending: !product }">{{ product?.name || '产品待确认' }}</h3>
      <p v-if="specs" class="line-spec">{{ specs }}</p>
    </template>
    <p class="line-raw"><span>原单</span>{{ line.raw.raw }}</p>

    <p v-if="line.match.reason" class="line-callout">{{ line.match.reason }}</p>
    <p v-if="status !== 'skipped' && line.match.excess_quantity" class="line-callout">超出发票数量 {{ line.match.excess_quantity }} 件</p>
    <template v-if="status !== 'skipped'">
      <p v-if="line.values.grade_source === 'inherited'" class="line-meta">等级 {{ line.values.grade_raw }} 沿用上一行，仍需核对</p>
      <p v-if="line.match.order" class="line-meta">
        {{ orderLabel(line.match.order) }}<span v-if="line.match.order.invoice_no"> · {{ line.match.order.invoice_no }}</span>
      </p>
      <p v-for="item in line.match.ignored_orders" :key="item.kind + item.ref" class="line-meta">
        单号 {{ item.ref }} 对应{{ item.kind === 'stock' ? '库存单' : '预售单' }}，不做发票对应
      </p>
      <details v-if="line.raw.doubts?.length" class="line-more">
        <summary>识别疑点 {{ line.raw.doubts.length }}</summary><ul><li v-for="(doubt, index) in line.raw.doubts" :key="index">{{ doubt }}</li></ul>
      </details>
      <details v-if="line.match.references?.length" class="line-more">
        <summary>相近规格 {{ line.match.references.length }}</summary><ul><li v-for="item in line.match.references" :key="item.sku_id">{{ item.name }}</li></ul>
      </details>
      <p v-if="status === 'matched'" class="line-target">去向 · {{ targetLabel(line) }}</p>
    </template>

    <footer v-if="editable && !line.batch_id" class="line-actions">
      <div v-if="status === 'matched'" class="line-toggles">
        <label class="pick">
          <input type="checkbox" :checked="line.selected" :disabled="busy" :aria-label="'勾选第 ' + line.line_no + ' 行'"
            @change="$emit('change', { selected: $event.target.checked })" />纳入本批
        </label>
        <label v-if="line.match.route !== 'inbound_only'" class="writeback">
          <el-switch :model-value="line.writeback_enabled" :disabled="busy" aria-label="回写或对应"
            @change="$emit('change', { writeback_enabled: $event })" />回写 / 对应
        </label>
      </div>
      <div class="line-buttons">
        <button class="line-btn" type="button" :disabled="busy" @click="$emit('edit')">修正</button>
        <button v-if="status === 'blocked'" class="line-btn" type="button" :disabled="busy" @click="$emit('change', { refresh: true })">重新匹配</button>
        <button v-if="needsDecision" class="line-btn primary" type="button" :disabled="busy" @click="$emit('choose')">
          {{ status === 'choose' ? '查看候选' : '去核对' }}
        </button>
      </div>
    </footer>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import { lineStatuses, orderLabel, targetLabel } from '../inboundLabels'

const props = defineProps({
  line: { type: Object, required: true }, editable: Boolean, busy: Boolean,
})
defineEmits(['change', 'edit', 'choose'])
const status = computed(() => props.line.match_status)
const state = computed(() => lineStatuses[status.value])
const tone = computed(() => props.line.batch_id ? 'info' : status.value === 'skipped' ? 'muted' : state.value.tone)
const needsDecision = computed(() => ['choose', 'confirm', 'decide'].includes(status.value))
const product = computed(() => props.line.match.product)
const specs = computed(() => {
  const { values, match } = props.line
  return [values.grade_raw, values.process_raw, match.length_in ? match.length_in + '″' : null,
    product.value?.color || values.color_raw, match.weight_g ? match.weight_g + ' g' : null,
  ].filter(Boolean).join(' · ')
})
</script>

<style src="../pills.css" scoped></style>
<style scoped>
.review-line {
  position: relative;
  padding: 16px 18px;
  border: 1px solid var(--border-color);
  border-radius: 18px;
  background: var(--card-bg);
  overflow: hidden;
  overflow-wrap: anywhere;
}
.review-line::before {
  content: '';
  position: absolute;
  inset: 14px auto 14px 0;
  width: 4px;
  border-radius: 0 4px 4px 0;
  background: var(--border-color);
}
.tone-success::before { background: var(--color-success); }
.tone-warning::before { background: var(--color-warning-text); }
.tone-danger::before { background: var(--color-danger); }
.tone-info::before { background: var(--color-info-text); }
.review-line.tone-warning { border-color: color-mix(in srgb, var(--color-warning-text) 30%, var(--border-color)); }
.review-line.tone-danger { border-color: color-mix(in srgb, var(--color-danger) 30%, var(--border-color)); }
.review-line.submitted, .review-line.tone-muted { background: color-mix(in srgb, var(--page-bg) 60%, var(--card-bg)); }

.line-top { display: flex; align-items: center; gap: 8px; }
.line-index {
  display: inline-flex; padding: 3px 8px; border: 1px solid var(--border-color); border-radius: 8px;
  font-size: 12px; font-weight: 700; color: var(--text-secondary);
}
.line-qty { margin-left: auto; font-size: 13px; color: var(--text-secondary); white-space: nowrap; }
.line-qty b { font-size: 20px; font-weight: 800; color: var(--text-primary); }
.line-product { margin: 12px 0 2px; font-size: 18px; font-weight: 800; line-height: 1.4; }
.line-product.pending { color: var(--text-secondary); font-weight: 700; }
.line-spec { margin: 0; font-size: 15px; line-height: 1.5; }
.line-raw {
  display: flex; gap: 8px; margin: 10px 0 0; padding: 8px 10px; border-radius: 10px; background: var(--page-bg);
  font-family: var(--font-mono, ui-monospace, monospace); font-size: 12px; line-height: 1.5; color: var(--text-secondary);
}
.line-raw span { flex-shrink: 0; font-family: var(--font-body, system-ui, sans-serif); font-weight: 650; }
.line-callout {
  margin: 10px 0 0; padding: 10px 12px; border-radius: 10px; font-size: 14px; font-weight: 650; line-height: 1.5;
  background: var(--page-bg); color: var(--text-primary);
}
.tone-warning .line-callout { background: var(--color-warning-bg); color: var(--color-warning-text); }
.tone-danger .line-callout { background: var(--color-danger-bg); color: var(--color-danger-text); }
.tone-muted .line-callout { font-weight: 500; color: var(--text-secondary); }
.line-meta, .line-target, .line-more { margin: 8px 0 0; font-size: 13px; line-height: 1.5; color: var(--text-secondary); }
.line-target { color: var(--color-success-text); font-weight: 600; }
.line-more summary { min-height: 44px; display: flex; align-items: center; cursor: pointer; }
.line-more ul { margin: 4px 0 0; padding-left: 18px; }

.line-actions {
  display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px;
  margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--border-color);
}
.line-toggles { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 16px; }
.pick, .writeback { display: inline-flex; align-items: center; gap: 8px; min-height: 44px; font-size: 14px; cursor: pointer; }
.pick input { width: 22px; height: 22px; margin: 0; accent-color: var(--button-primary); cursor: pointer; }
.line-buttons { display: flex; gap: 8px; margin-left: auto; }
.line-btn {
  min-height: 44px; padding: 0 16px; border: 1px solid var(--border-color); border-radius: 12px;
  background: var(--card-bg); color: var(--text-primary); font: inherit; font-size: 14px; font-weight: 650; cursor: pointer;
  transition: transform 140ms cubic-bezier(.23, 1, .32, 1), background-color 160ms ease, border-color 160ms ease;
}
.line-btn.primary { border-color: var(--button-primary); background: var(--button-primary); color: var(--button-surface); }
.line-btn:active:not(:disabled) { transform: scale(.97); }
.line-btn:disabled { background: var(--button-disabled-bg); border-color: var(--button-border); color: var(--button-disabled-text); cursor: not-allowed; }
.line-btn:focus-visible, .pick input:focus-visible { outline: 3px solid var(--button-focus, var(--button-primary)); outline-offset: 2px; }
@media (hover: hover) and (pointer: fine) {
  .line-btn:hover:not(:disabled) { border-color: var(--button-primary-hover); }
  .line-btn.primary:hover:not(:disabled) { background: var(--button-primary-hover); }
}
@media (prefers-reduced-motion: reduce) {
  .line-btn { transition: none; }
  .line-btn:active { transform: none; }
}
</style>
