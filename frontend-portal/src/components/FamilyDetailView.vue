<script setup>
import ProductImage from './ProductImage.vue'
import SelectionPanel from './SelectionPanel.vue'
import { computed, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import { unitPrice as price, beijingTime } from '../presentation.mjs'
import { minimumQuantity } from '../state/checkout.mjs'
import { colorGroups, formatGrams, gradeOptions, lengthOptions, mergeAvailability, resolveSelection, stepQuantity, stockLabel } from '../state/family.mjs'
const POLL_MS = 30000
const props = defineProps({ api: { type: Object, required: true }, session: { type: Object, required: true },
  checkout: { type: Object, required: true }, state: { type: Object, required: true }, code: { type: String, required: true } })
const emit = defineEmits(['collection', 'checkout'])
const family = shallowRef(null), variants = shallowRef([]), busy = ref(true), error = ref(null)
const wanted = ref({}), quantity = ref(1), addError = ref(null), added = ref('')
let controller, pollController, timer, disposed = false
const selection = computed(() => resolveSelection(variants.value, wanted.value))
const variant = computed(() => selection.value.variant)
const canOrder = computed(() => props.session.capabilities.place_order && variant.value?.availability === 'available' && variant.value.unit_price != null && minimumQuantity(variant.value) !== null)
const lineGrams = computed(() => variant.value ? Number(variant.value.unit_weight_grams) * (Number(quantity.value) || 0) : null)

async function load() {
  controller?.abort(); controller = new AbortController(); busy.value = true; error.value = null
  try {
    const data = await props.api.family(props.code, controller.signal)
    if (disposed) return
    family.value = data; variants.value = data.variants
    quantity.value = minimumQuantity(resolveSelection(data.variants, wanted.value).variant || {}) ?? 1
  } catch (problem) { if (!['STALE_SCOPE', 'REQUEST_ABORTED'].includes(problem.code)) error.value = problem }
  finally { if (!disposed) busy.value = false }
}
async function poll() {
  if (disposed || pollController || document.visibilityState !== 'visible' || !family.value) return
  pollController = new AbortController()
  try {
    const data = await props.api.familyAvailability(props.code, pollController.signal)
    if (!disposed) variants.value = mergeAvailability(variants.value, data.items)
  } catch { /* Keep the last verified view; the quote re-validates stock anyway. */ }
  finally { pollController = null }
}
function choose(patch) {
  wanted.value = { ...wanted.value, ...patch }; addError.value = null; added.value = ''
  quantity.value = minimumQuantity(selection.value.variant || {}) ?? 1
}
function step(direction) {
  const item = variant.value
  quantity.value = stepQuantity(quantity.value, item.step_qty, minimumQuantity(item), direction); addError.value = null
}
function add() {
  addError.value = null
  try {
    props.checkout.add(variant.value, quantity.value)
    added.value = `${variant.value.grade_label} · ${variant.value.length}" · ${variant.value.color_code} added.`
    quantity.value = minimumQuantity(variant.value)
  } catch (problem) { addError.value = problem }
}
onMounted(() => { load(); timer = setInterval(poll, POLL_MS); document.addEventListener('visibilitychange', poll) })
onBeforeUnmount(() => { disposed = true; clearInterval(timer); document.removeEventListener('visibilitychange', poll); controller?.abort(); pollController?.abort() })
</script>

<template>
  <section class="family-page">
    <a href="/collection" class="text-button family-back" @click.prevent="emit('collection')">← All products</a>
    <div v-if="error" class="empty-state" role="alert"><h2>We couldn’t load this product.</h2><p>{{ error.message }}</p><button class="button primary" @click="load">Try again</button><small v-if="error.traceId">Reference: {{ error.traceId }}</small></div>
    <div v-else-if="busy" class="family-layout" aria-hidden="true"><div class="family-gallery product-skeleton"><div></div></div><div class="product-skeleton"><span></span><span></span></div></div>
    <div v-else-if="family && variant" class="family-layout">
      <div class="family-gallery"><div class="family-image"><ProductImage :url="variant.swatch_url || variant.image_url" :alt="`${family.display_name}, ${variant.color_code}`" /></div><p class="family-caption"><strong>{{ variant.color_code }}</strong><span v-if="variant.color_label !== variant.color_code"> · {{ variant.color_label }}</span><span class="muted"> · {{ variant.grade_label }} · {{ variant.length }}"</span></p></div>
      <div class="family-options">
        <h1>{{ family.display_name }}</h1>
        <p v-if="session.capabilities.view_price" class="detail-price">{{ price(variant.unit_price) }}<small v-if="variant.unit_price != null"> / {{ variant.sale_unit }}</small></p>
        <fieldset class="option-row"><legend>Ratio</legend><button v-for="option in gradeOptions(variants)" :key="option.value" type="button" :class="['option-chip', { muted: !option.available }]" :aria-pressed="option.value === selection.grade" @click="choose({ grade: option.value })">{{ option.label }}</button></fieldset>
        <fieldset class="option-row"><legend>Length</legend><button v-for="option in lengthOptions(variants, selection.grade)" :key="option.value" type="button" :class="['option-chip', { muted: !option.available }]" :aria-pressed="option.value === selection.length" @click="choose({ length: option.value })">{{ option.value }}"</button></fieldset>
        <fieldset class="option-row colors"><legend>Color <span class="muted">· {{ variant.color_code }}</span></legend>
          <div v-for="group in colorGroups(variants, selection.grade, selection.length)" :key="group.type" class="color-group"><span class="small muted">{{ group.label }}</span><div>
            <button v-for="color in group.colors" :key="color.color_key" type="button" :class="['swatch-chip', { unavailable: color.availability !== 'available' }]" :aria-pressed="color.color_key === selection.colorKey" :aria-label="`${color.color_code}, ${stockLabel(color)}`" :title="color.color_label" @click="choose({ colorKey: color.color_key })"><span class="swatch-thumb"><ProductImage :url="color.swatch_url" alt="" /></span><span>{{ color.color_code }}</span></button>
          </div></div>
        </fieldset>
        <p :class="['stock-state', variant.availability]" role="status"><span aria-hidden="true">●</span> {{ stockLabel(variant) }}<span v-if="variant.inventory_observed_at" class="muted"> · checked {{ beijingTime(variant.inventory_observed_at) }}</span></p>
        <div v-if="canOrder" class="family-purchase">
          <div class="purchase-row"><div class="stepper"><button type="button" class="icon-button" aria-label="Decrease quantity" :disabled="Number(quantity) <= minimumQuantity(variant)" @click="step(-1)">−</button><label><span class="sr-only">Quantity</span><input v-model="quantity" type="number" inputmode="numeric" :min="minimumQuantity(variant)" :step="variant.step_qty" max="10000" @input="addError = null" /></label><button type="button" class="icon-button" aria-label="Increase quantity" @click="step(1)">+</button></div>
          <button type="button" class="button primary" @click="add">Add to selection</button></div>
          <p class="small muted">{{ variant.sale_unit }} · minimum {{ variant.min_order_qty }}, in steps of {{ variant.step_qty }} · {{ formatGrams(lineGrams) }}</p>
          <p v-if="addError" class="alert error small" role="alert">{{ addError.message }}</p>
          <p v-if="added" class="added-note small" role="status"><span aria-hidden="true">✓</span> {{ added }}</p>
        </div>
        <p v-else-if="!session.capabilities.place_order" class="small muted">Your access is for browsing. Contact your representative to request ordering access.</p>
        <p class="small muted">Availability is not a stock reservation. Final quantities and shipping are confirmed by your representative.</p>
      </div>
      <SelectionPanel v-if="session.capabilities.place_order" class="family-selection" :checkout="checkout" :state="state" @checkout="emit('checkout')" />
    </div>
    <div v-else class="empty-state"><h2>This product is not available right now.</h2><button class="button secondary" @click="emit('collection')">Back to collection</button></div>
  </section>
</template>
