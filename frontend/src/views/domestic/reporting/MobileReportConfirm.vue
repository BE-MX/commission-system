<template>
  <div class="confirm-mask" role="presentation" @click.self="emit('cancel')">
    <section class="confirm-sheet" role="dialog" aria-modal="true" aria-labelledby="report-confirm-title" @keydown.esc="cancel">
      <header class="sheet-header">
        <div>
          <span class="eyebrow">REPORT CONFIRMATION</span>
          <h2 id="report-confirm-title">确认报工信息</h2>
        </div>
        <button ref="closeButton" class="icon-button" type="button" aria-label="取消报工" :disabled="submitting" @click="cancel">×</button>
      </header>

      <div class="sheet-body">
        <dl class="info-grid">
          <div class="info-primary"><dt>产品</dt><dd>{{ scan.product_name || '-' }}</dd></div>
          <div><dt>客户</dt><dd>{{ scan.customer_name || '-' }}</dd></div>
          <div><dt>订单</dt><dd>{{ orderLabel }}</dd></div>
          <div v-if="isUnit"><dt>单件编号</dt><dd>{{ scan.unit_code || '-' }}</dd></div>
          <div class="info-primary"><dt>当前工序</dt><dd>{{ nextStep.process_name || '-' }}</dd></div>
        </dl>

        <section class="quantity-card">
          <div class="quantity-heading">
            <div>
              <span class="section-label">报工数量</span>
              <p>{{ isUnit ? '单件二维码固定报 1 件' : `本次最多可报 ${maxQty} 件` }}</p>
            </div>
            <button v-if="!isUnit" type="button" class="all-button" @click="setQty(maxQty)">全部</button>
          </div>
          <div class="quantity-control">
            <button type="button" aria-label="数量减一" :disabled="isUnit || qty <= 1" @click="setQty(qty - 1)">−</button>
            <input
              ref="qtyInput"
              v-model="qtyText"
              inputmode="numeric"
              pattern="[0-9]*"
              aria-label="报工数量"
              :disabled="isUnit"
              @input="onQtyInput"
              @blur="normalizeQty"
            />
            <button type="button" aria-label="数量加一" :disabled="isUnit || qty >= maxQty" @click="setQty(qty + 1)">＋</button>
          </div>
          <p class="quantity-tip">{{ isUnit ? '同一道工序重复扫描会被后端拦截。' : '默认整批报工；改小即可拆批，剩余数量以后继续扫同一张卡。' }}</p>
        </section>

        <details v-if="requirements.length || images.length" class="detail-panel" open>
          <summary>图文要求</summary>
          <dl v-if="requirements.length" class="requirement-list">
            <div v-for="item in requirements" :key="item.label"><dt>{{ item.label }}</dt><dd>{{ item.value }}</dd></div>
          </dl>
          <div v-if="images.length" class="image-strip">
            <div v-for="(image, index) in images" :key="image.path" class="image-slot">
              <a v-if="image.url" :href="image.url" target="_blank" rel="noopener">
                <img :src="image.url" :alt="`参考图 ${index + 1}`" />
              </a>
              <button v-else type="button" :disabled="image.loading" @click="emit('load-image', index)">
                {{ image.loading ? '加载中…' : image.error ? '加载失败，重试' : `加载参考图 ${index + 1}` }}
              </button>
            </div>
          </div>
        </details>

        <details v-if="steps.length" class="detail-panel">
          <summary>工序进度 · {{ finishedSteps }}/{{ steps.length }}</summary>
          <ol class="timeline">
            <li v-for="step in steps" :key="step.progress_id" :class="{ done: step.completed_qty >= step.order_qty }">
              <span class="step-dot"></span>
              <div><strong>第 {{ step.step_order }} 道 · {{ step.process_name }}</strong><span>{{ step.completed_qty }} / {{ step.order_qty }} 件</span></div>
            </li>
          </ol>
        </details>
      </div>

      <footer class="sheet-actions">
        <button type="button" class="secondary-action" :disabled="submitting" @click="cancel">取消</button>
        <button type="button" class="primary-action" :disabled="submitting || blocked" @click="confirm">
          {{ submitting ? '正在提交…' : blocked ? '请先重试待确认提交' : `确认报 ${qty} 件` }}
        </button>
      </footer>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'

const props = defineProps({
  scan: { type: Object, required: true },
  images: { type: Array, default: () => [] },
  submitting: { type: Boolean, default: false },
  blocked: { type: Boolean, default: false },
})
const emit = defineEmits(['cancel', 'confirm', 'load-image'])

const qty = ref(1)
const qtyText = ref('1')
const qtyInput = ref(null)
const closeButton = ref(null)
const nextStep = computed(() => props.scan.next_step || {})
const maxQty = computed(() => Math.max(1, Number(nextStep.value.reportable_qty || 1)))
const isUnit = computed(() => props.scan.report_mode === 'unit')
const steps = computed(() => props.scan.steps || [])
const finishedSteps = computed(() => steps.value.filter(step => step.order_qty > 0 && step.completed_qty >= step.order_qty).length)
const orderLabel = computed(() => [props.scan.domestic_no, props.scan.order_no].filter(Boolean).join(' · ') || '-')
const requirements = computed(() => [
  { label: '发型', value: props.scan.hairstyle },
  { label: '颜色', value: props.scan.color },
  { label: '要求', value: props.scan.style_requirement },
  { label: '备注', value: props.scan.remark },
].filter(item => item.value))

watch(() => props.scan, () => setQty(isUnit.value ? 1 : maxQty.value), { immediate: true })

onMounted(async () => {
  await nextTick()
  if (isUnit.value) closeButton.value?.focus()
  else qtyInput.value?.focus()
})

function setQty(value) {
  const normalized = Math.min(maxQty.value, Math.max(1, Number(value) || 1))
  qty.value = normalized
  qtyText.value = String(normalized)
}

function onQtyInput(event) {
  qty.value = Number.parseInt(event.target.value, 10) || 0
}

function normalizeQty() {
  setQty(qty.value)
}

function confirm() {
  if (props.submitting || props.blocked) return
  normalizeQty()
  emit('confirm', qty.value)
}

function cancel() {
  if (!props.submitting) emit('cancel')
}
</script>

<style scoped>
.confirm-mask { position: fixed; top: 0; right: 0; bottom: 0; left: 0; z-index: 1000; display: flex; align-items: flex-end; justify-content: center; background: rgba(20, 18, 16, 0.58); }
.confirm-sheet { display: flex; width: 100%; max-width: 720px; width: min(100%, 720px); max-height: 92vh; flex-direction: column; overflow: hidden; border: 1px solid var(--dash-glass-border); border-radius: 24px 24px 0 0; background: var(--card-bg); box-shadow: var(--dash-glass-shadow-hover); animation: sheet-in 240ms var(--ease-out-strong); }
.sheet-header { display: flex; align-items: center; justify-content: space-between; padding: 20px 20px 14px; border-bottom: 1px solid var(--border-color); }
.eyebrow, .section-label { color: var(--color-primary); font: 700 10px/1 var(--font-display); letter-spacing: .12em; }
.sheet-header h2 { margin: 5px 0 0; color: var(--text-primary); font: 800 21px/1.2 var(--font-display); }
.icon-button { width: 40px; height: 40px; border: 0; border-radius: 50%; color: var(--text-secondary); background: var(--toolbar-bg); font-size: 27px; }
.sheet-body { overflow-y: auto; padding: 18px 18px 8px; }
.info-grid { display: block; display: grid; margin: 0; gap: 2px; }
.info-grid > div { display: flex; display: grid; grid-template-columns: 84px 1fr; padding: 9px 0; border-bottom: 1px solid var(--border-color); }
.info-grid dt { flex: 0 0 84px; }
.info-grid dt, .requirement-list dt { color: var(--text-secondary); font-size: 12px; }
.info-grid dd, .requirement-list dd { margin: 0; color: var(--text-primary); font-size: 14px; font-weight: 600; overflow-wrap: anywhere; }
.info-grid .info-primary dd { color: var(--color-success-text); font-size: 16px; }
.quantity-card { margin-top: 16px; padding: 16px; border: 1px solid var(--border-color); border-radius: 16px; background: var(--toolbar-bg); }
.quantity-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.quantity-heading p, .quantity-tip { margin: 5px 0 0; color: var(--text-secondary); font-size: 12px; }
.all-button { min-width: 58px; height: 34px; border: 1px solid var(--color-primary); border-radius: 10px; color: var(--color-primary); background: var(--color-primary-light); font-weight: 700; }
.quantity-control { display: flex; display: grid; grid-template-columns: 54px 1fr 54px; gap: 8px; margin-top: 14px; }
.quantity-control button, .quantity-control input { height: 54px; border: 1px solid var(--border-color); border-radius: 12px; background: var(--card-bg); }
.quantity-control button { width: 54px; flex: 0 0 54px; color: var(--color-primary); font-size: 25px; font-weight: 700; }
.quantity-control button:disabled { color: var(--text-muted); }
.quantity-control input { min-width: 0; flex: 1; color: var(--text-primary); font: 800 25px/1 var(--font-display); text-align: center; }
.detail-panel { margin-top: 14px; border: 1px solid var(--border-color); border-radius: 14px; background: var(--card-bg); }
.detail-panel summary { padding: 14px 16px; color: var(--text-primary); font-size: 14px; font-weight: 700; cursor: pointer; }
.requirement-list { margin: 0; padding: 0 16px 8px; }
.requirement-list > div { display: flex; display: grid; grid-template-columns: 62px 1fr; gap: 8px; padding: 8px 0; }
.requirement-list dt { flex: 0 0 62px; }
.image-strip { display: flex; gap: 9px; overflow-x: auto; padding: 4px 16px 16px; }
.image-slot { flex: 0 0 96px; }
.image-strip img, .image-slot > button { width: 96px; height: 96px; border-radius: 12px; object-fit: cover; }
.image-slot > button { padding: 8px; border: 1px dashed var(--border-hover); color: var(--text-secondary); background: var(--toolbar-bg); font-size: 11px; line-height: 1.4; }
.timeline { margin: 0; padding: 0 16px 12px; list-style: none; }
.timeline li { display: flex; display: grid; grid-template-columns: 18px 1fr; gap: 8px; padding: 8px 0; }
.timeline li > div { flex: 1; }
.timeline li div { display: flex; justify-content: space-between; gap: 8px; color: var(--text-secondary); font-size: 12px; }
.timeline strong { color: var(--text-primary); font-size: 13px; }
.step-dot { width: 10px; height: 10px; margin-top: 3px; border: 2px solid var(--border-hover); border-radius: 50%; }
.timeline li.done .step-dot { border-color: var(--color-success); background: var(--color-success); }
.sheet-actions { display: flex; display: grid; grid-template-columns: 1fr 2fr; gap: 10px; padding: 12px 18px; padding: 12px 18px calc(12px + env(safe-area-inset-bottom)); border-top: 1px solid var(--border-color); background: var(--card-bg); }
.sheet-actions button { min-height: 48px; border-radius: 12px; font: 700 14px/1 var(--font-display); }
.secondary-action { flex: 1; border: 1px solid var(--border-color); color: var(--text-secondary); background: var(--card-bg); }
.primary-action { flex: 2; border: 1px solid var(--color-primary); color: var(--card-bg); background: linear-gradient(135deg, var(--color-primary), var(--color-primary-hover)); }
button:disabled { opacity: .55; }
@keyframes sheet-in { from { opacity: 0; transform: translateY(24px); } to { opacity: 1; transform: translateY(0); } }
@supports not (display: grid) {
  .quantity-control > * + *, .sheet-actions > * + * { margin-left: 8px; }
  .info-grid dd, .requirement-list dd, .timeline li > div { min-width: 0; }
}
@media (prefers-reduced-motion: reduce) { .confirm-sheet { animation: none; } }
</style>
