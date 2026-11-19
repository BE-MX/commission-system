<template>
  <el-drawer :model-value="open" title="核对汇总" direction="btt" size="640px" class="factory-candidate-sheet" append-to-body @close="$emit('close')">
    <section class="summary">
      <div class="summary-hero">
        <span>本批入库</span>
        <strong>{{ selected.length }} 行 · {{ quantity }} 件</strong>
        <small v-if="remaining">另有 {{ remaining }} 行留在草稿</small>
      </div>
      <p v-if="!note.delivery_no" class="summary-block">单据编号待确认，确认后才能同步入库</p>
      <p v-if="note.duplicate" class="summary-block">疑似重拍：可能是同一张单，请先处理</p>
      <ul class="summary-groups">
        <li v-for="group in groups" :key="group.label"><span>{{ group.label }}</span><b>{{ group.quantity }} 件</b></li>
      </ul>
      <template v-if="canPreview">
        <p v-if="loadingPreview" class="summary-status" role="status">正在核对分配…</p>
        <div v-if="previewError" class="summary-block" role="alert">
          <p>{{ previewError }}</p>
          <button class="summary-secondary" type="button" @click="loadPreview">重新核对</button>
        </div>
        <template v-if="preview">
          <h3>分配明细</h3>
          <ul class="allocation-list">
            <li v-for="line in preview.lines" :key="line.id" :class="{ blocked: line.blocking_reason }">
              <div class="allocation-head"><span>第 {{ line.line_no }} 行 · {{ line.name }}</span><b>{{ line.quantity }} 件</b></div>
              <p v-if="line.blocking_reason" class="allocation-reason">{{ line.blocking_reason }}</p>
              <ul v-if="line.allocations.length || line.unallocated_qty">
                <li v-for="(allocation, index) in line.allocations" :key="index">
                  {{ allocation.target_kind === 'invoice' || allocation.target_kind === 'invoice_item' ? '发票生产单' : '生产备货单' }}
                  {{ allocation.order_ref || allocation.order_id }} · {{ allocation.quantity }} 件
                </li>
                <li v-if="line.unallocated_qty">{{ line.unallocated_qty }} 件{{ line.route === 'cross' ? '当前未分配' : '只入库' }}</li>
              </ul>
            </li>
          </ul>
          <form v-if="!blocked" class="price-form" @submit.prevent="start">
            <h3>采购单价</h3>
            <p class="summary-status">每个 SKU 填写采购单价（USD 整数）。本批次将生成一张采购单和一张入库单。</p>
            <label v-for="item in products" :key="item.key" class="sku-price">
              <span><b>{{ item.name }}</b><small>SKU {{ item.sku_id }} · {{ item.quantity }} 件</small></span>
              <el-input v-model.trim="prices[item.key]" type="text" inputmode="numeric"
                :aria-label="'SKU ' + item.sku_id + ' 的 USD 采购单价'" placeholder="USD 单价"
                :disabled="submitting" />
            </label>
            <label v-if="preview.requires_cross_confirmation" class="check-row">
              <input v-model="crossConfirmed" type="checkbox" :disabled="submitting" />同意按回写时的可用余量跨生产备货单分配
            </label>
            <button v-any-permission="['factory_inbound:write', 'factory_inbound:admin']" class="summary-submit"
              type="submit" :disabled="!validPrices || !crossReady || submitting">
              {{ submitting ? '正在同步入库…' : '确认并同步入库' }}
            </button>
            <p v-if="submitting" class="summary-status" role="status">正在同步并核对小满单据，完成后会刷新批次进度。</p>
          </form>
        </template>
      </template>
    </section>
  </el-drawer>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { factoryInboundApi } from '@/api/factoryInbound'
import { msgWarning } from '@/utils/feedback'
import { targetLabel } from '../inboundLabels'

const props = defineProps({ note: { type: Object, required: true }, open: Boolean, syncEnabled: Boolean })
const emit = defineEmits(['close', 'batch-checked'])
const selected = computed(() => props.note.lines.filter(row => row.selected && !row.batch_id && row.match_status === 'matched'))
const remaining = computed(() => props.note.lines.filter(row => !row.batch_id && !row.selected && row.match_status !== 'skipped').length)
const quantity = computed(() => selected.value.reduce((sum, row) => sum + row.values.quantity, 0))
const groups = computed(() => {
  const quantities = new Map()
  for (const row of selected.value) {
    const label = targetLabel(row)
    quantities.set(label, (quantities.get(label) || 0) + row.values.quantity)
  }
  return [...quantities].map(([label, count]) => ({ label, quantity: count }))
})
const preview = shallowRef(null)
const loadingPreview = ref(false)
const previewError = ref('')
const submitting = ref(false)
const prices = ref({})
const crossConfirmed = ref(false)
const canPreview = computed(() => props.syncEnabled && props.note.editable && props.note.delivery_no
  && !props.note.duplicate && selected.value.length > 0)
const blocked = computed(() => preview.value?.lines.some(line => line.blocking_reason))
const crossReady = computed(() => !preview.value?.requires_cross_confirmation || crossConfirmed.value)
const products = computed(() => {
  const bySku = new Map()
  for (const line of preview.value?.lines || []) {
    if (!line.sku_id) continue
    const key = line.product_id + ':' + line.sku_id
    const previous = bySku.get(key)
    bySku.set(key, { ...line, key, quantity: (previous?.quantity || 0) + line.quantity })
  }
  return [...bySku.values()]
})
const validPrices = computed(() => products.value.length > 0 && products.value.every(({ key }) => {
  const value = prices.value[key] || ''
  return /^[1-9]\d*$/.test(value) && Number.isSafeInteger(Number(value))
}))
let previewRequest
let idempotencyKey
let alive = true

function selection() {
  return { version: props.note.version, line_ids: selected.value.map(line => line.id) }
}

function errorText(error, fallback) {
  const detail = error.response?.data?.detail
  if (typeof detail === 'string') return detail
  return typeof detail?.message === 'string' ? detail.message : fallback
}

async function loadPreview() {
  previewRequest?.abort()
  preview.value = null
  previewError.value = ''
  prices.value = {}
  crossConfirmed.value = false
  if (!props.open || !canPreview.value) {
    loadingPreview.value = false
    return
  }
  const controller = new AbortController()
  previewRequest = controller
  loadingPreview.value = true
  try {
    const result = await factoryInboundApi.previewBatch(props.note.id, selection(), {
      signal: controller.signal, suppressToast: true,
    })
    if (!controller.signal.aborted) {
      const random = crypto.getRandomValues(new Uint8Array(16))
      idempotencyKey = Array.from(random, value => value.toString(16).padStart(2, '0')).join('')
      preview.value = result.data
    }
  } catch (error) {
    if (!controller.signal.aborted) previewError.value = errorText(error, '无法核对批次，请重试。')
  } finally {
    if (!controller.signal.aborted) loadingPreview.value = false
  }
}

async function start() {
  if (submitting.value || blocked.value || !validPrices.value || !crossReady.value || !canPreview.value) return
  const noteId = props.note.id
  submitting.value = true
  try {
    await factoryInboundApi.startBatch(noteId, {
      ...selection(),
      preview_digest: preview.value.preview_digest,
      idempotency_key: idempotencyKey,
      unit_prices: products.value.map(({ product_id, sku_id, key }) => ({
        product_id, sku_id, unit_price: Number(prices.value[key]),
      })),
      confirm_cross: crossConfirmed.value,
    }, { suppressToast: true })
  } catch (error) {
    if (alive && props.note.id === noteId) {
      msgWarning(errorText(error, '提交结果待核对，请查看批次进度后再操作。'))
    }
  } finally {
    submitting.value = false
    if (alive && props.note.id === noteId) {
      emit('close')
      emit('batch-checked')
    }
  }
}

watch([() => props.open, () => props.note.id, () => props.note.version, canPreview], loadPreview, { immediate: true })
onBeforeUnmount(() => {
  alive = false
  previewRequest?.abort()
})
</script>

<style scoped>
.summary { max-width: 640px; margin-inline: auto; display: grid; gap: 12px; padding-bottom: env(safe-area-inset-bottom); overflow-wrap: anywhere; }
.summary h3 { margin: 8px 0 0; font-size: 15px; font-weight: 750; }
.summary-hero { display: grid; gap: 2px; padding: 16px 18px; border-radius: 16px; background: var(--color-gold-soft); }
.summary-hero span, .summary-hero small { font-size: 12px; color: var(--text-secondary); }
.summary-hero strong { font-size: 24px; font-weight: 800; }
.summary-block { margin: 0; padding: 10px 12px; border-radius: 10px; background: var(--color-warning-bg); color: var(--color-warning-text); font-size: 14px; font-weight: 600; }
.summary-block p { margin: 0 0 8px; }
.summary-status { margin: 0; font-size: 13px; line-height: 1.6; color: var(--text-secondary); }
.summary-groups, .allocation-list { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.summary-groups li { display: flex; justify-content: space-between; gap: 12px; padding: 10px 14px; border: 1px solid var(--border-color); border-radius: 12px; font-size: 14px; }
.allocation-list > li { padding: 12px 14px; border-radius: 12px; background: var(--page-bg); font-size: 13px; }
.allocation-list > li.blocked { background: var(--color-danger-bg); }
.allocation-head { display: flex; justify-content: space-between; gap: 12px; font-size: 14px; font-weight: 650; }
.allocation-head b { white-space: nowrap; }
.allocation-reason { margin: 6px 0 0; color: var(--color-danger-text); font-weight: 600; }
.allocation-list ul { margin: 6px 0 0; padding-left: 18px; line-height: 1.7; color: var(--text-secondary); }
.price-form { display: grid; gap: 12px; }
.check-row { display: flex; align-items: center; gap: 10px; min-height: 44px; font-size: 14px; cursor: pointer; }
.check-row input { width: 22px; height: 22px; margin: 0; flex-shrink: 0; accent-color: var(--button-primary); cursor: pointer; }
.check-row input:focus-visible { outline: 3px solid var(--button-focus, var(--button-primary)); outline-offset: 2px; }
.sku-price { display: grid; grid-template-columns: minmax(0, 1fr) 120px; align-items: center; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--border-color); }
.sku-price span { display: grid; gap: 2px; font-size: 14px; }
.sku-price small { font-size: 12px; color: var(--text-secondary); }
.summary-submit, .summary-secondary {
  min-height: 52px; border-radius: 14px; font: inherit; font-size: 15px; font-weight: 650; cursor: pointer;
  transition: transform 140ms cubic-bezier(.23, 1, .32, 1), background-color 160ms ease;
}
.summary-submit { border: 1px solid var(--button-primary); background: var(--button-primary); color: var(--button-surface); }
.summary-secondary { min-height: 44px; padding: 0 16px; border: 1px solid var(--border-color); background: var(--card-bg); color: var(--text-primary); }
.summary-submit:active:not(:disabled), .summary-secondary:active:not(:disabled) { transform: scale(.97); }
.summary-submit:disabled { background: var(--button-disabled-bg); border-color: var(--button-border); color: var(--button-disabled-text); cursor: not-allowed; }
.summary-submit:focus-visible, .summary-secondary:focus-visible { outline: 3px solid var(--button-focus, var(--button-primary)); outline-offset: 2px; }
@media (hover: hover) and (pointer: fine) { .summary-submit:hover:not(:disabled) { background: var(--button-primary-hover); } }
@media (prefers-reduced-motion: reduce) { .summary-submit, .summary-secondary { transition: none; } .summary-submit:active, .summary-secondary:active { transform: none; } }
</style>
