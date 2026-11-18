<template>
  <el-drawer :model-value="open" title="核对汇总" direction="btt" size="640px" class="factory-candidate-sheet" append-to-body @close="$emit('close')">
    <section class="summary">
      <p><strong>{{ selected.length }} 行 · {{ quantity }} 件</strong></p>
      <p v-if="!note.delivery_no">单据编号待确认</p>
      <p v-if="note.duplicate">疑似重复单据待处理</p>
      <p v-if="remaining">另有 {{ remaining }} 行留在草稿</p>
      <ul>
        <li v-for="group in groups" :key="group.label">{{ group.label }} · {{ group.quantity }} 件</li>
      </ul>
      <template v-if="canPreview">
        <p v-if="loadingPreview" role="status">正在核对分配…</p>
        <div v-if="previewError" role="alert">
          <p>{{ previewError }}</p>
          <GlassButton @click="loadPreview">重新核对</GlassButton>
        </div>
        <template v-if="preview">
          <ul>
            <li v-for="line in preview.lines" :key="line.id">
              第 {{ line.line_no }} 行 · {{ line.name }} · {{ line.quantity }} 件
              <span v-if="line.blocking_reason"> · {{ line.blocking_reason }}</span>
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
            <p>每个 SKU 填写采购单价（USD 整数）。本批次将生成一张采购单和一张入库单。</p>
            <label v-for="item in products" :key="item.key" class="sku-price">
              <span>{{ item.name }} · SKU {{ item.sku_id }} · {{ item.quantity }} 件</span>
              <el-input v-model.trim="prices[item.key]" type="text" inputmode="numeric"
                :aria-label="'SKU ' + item.sku_id + ' 的 USD 采购单价'" placeholder="USD 单价"
                :disabled="submitting" />
            </label>
            <el-checkbox v-if="preview.requires_cross_confirmation" v-model="crossConfirmed" :disabled="submitting">
              同意按回写时的可用余量跨生产备货单分配
            </el-checkbox>
            <GlassButton v-any-permission="['factory_inbound:write', 'factory_inbound:admin']" variant="primary"
              native-type="submit" :loading="submitting" :disabled="!validPrices || !crossReady || submitting">
              确认并同步入库
            </GlassButton>
            <p v-if="submitting" role="status">正在同步并核对小满单据，完成后会刷新批次进度。</p>
          </form>
        </template>
      </template>
    </section>
  </el-drawer>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
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
.summary { max-width: 700px; margin-inline: auto; }
.summary p { margin-top: 0; }
.summary ul { padding-left: 18px; line-height: 1.7; }
.price-form { display: grid; gap: 12px; }
.price-form > .glass-button { justify-self: start; }
.sku-price { display: grid; grid-template-columns: minmax(0, 1fr) 110px; align-items: center; gap: 12px; }
.sku-price span { overflow-wrap: anywhere; }
</style>
