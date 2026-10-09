<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { unitPrice, money, beijingTime } from '../presentation.mjs'
import { minimumQuantity, quoteDeadline } from '../state/checkout.mjs'
import ProposalDiff from './ProposalDiff.vue'
const props = defineProps({ checkout: { type: Object, required: true }, state: { type: Object, required: true }, submission: { type: Object, required: true }, orderingEnabled: { type: Boolean, required: true } })
const emit = defineEmits(['collection', 'order'])
const error = ref(null), clock = ref(Date.now()), review = ref(null), errorSummary = ref(null)
watch(() => error.value || props.state.error, async problem => {
  if (problem) { await nextTick(); errorSummary.value?.focus() }
})
const timer = setInterval(() => { clock.value = Date.now() }, 1000)
onBeforeUnmount(() => clearInterval(timer))
const pending = computed(() => ['submitting', 'checking', 'uncertain'].includes(props.state.submission.status))
const browsingOnly = computed(() => !props.orderingEnabled && !pending.value && !props.state.receipt)
const expired = computed(() => props.state.quote && !(quoteDeadline(props.state.quote.expires_at) > clock.value))
function changedLine(line) {
  const original = props.state.lines.find(item => item.item_id === line.item_id)
  const display = line.display_snapshot
  return !original || original.unit_price !== line.unit_price || original.quantity !== line.quantity ||
    ['model_name', 'color_name', 'customer_sku'].some(key => original[key] !== display[key]) ||
    original.length_display !== String(display.length) || original.weight_display !== String(display.weight) || original.sale_unit !== display.unit
}
const fields = [
  ['contact_name', 'Contact name', 'name', 100, true], ['phone', 'Phone number', 'tel', 40, true],
  ['address_line1', 'Address line 1', 'address-line1', 200, true], ['address_line2', 'Address line 2 (optional)', 'address-line2', 200, false],
  ['city', 'City', 'address-level2', 100, false], ['region', 'State / region', 'address-level1', 100, false],
  ['postal_code', 'Postal code', 'postal-code', 32, false], ['country_code', 'Country code (e.g. US, GB)', 'country', 2, true],
]
async function act(action) {
  error.value = null
  try { await action() } catch (problem) { if (problem.code !== 'STALE_SCOPE') error.value = problem }
}
function quantity(line, event) {
  act(() => props.checkout.quantity(line.item_id, event.target.value))
  event.target.value = props.state.lines.find(item => item.item_id === line.item_id)?.quantity ?? line.quantity
}
async function getQuote() {
  await act(() => props.checkout.quote())
  if (props.state.quote) review.value?.focus()
}
</script>

<template>
  <section class="collection-page checkout-page">
    <header class="collection-heading"><div><p class="eyebrow gold">YOUR NEXT CHAPTER</p><h1>{{ browsingOnly ? 'Your collection.' : 'Your selection.' }}</h1><p class="muted">{{ browsingOnly ? 'Explore the products selected for your company.' : 'A considered request, with every detail in place.' }}</p></div><button class="text-button" @click="emit('collection')">← Continue browsing</button></header>
    <div v-if="error || state.error" ref="errorSummary" class="alert error" role="alert" tabindex="-1"><p>{{ (error || state.error).message }}</p><small v-if="(error || state.error).traceId">Reference: {{ (error || state.error).traceId }}</small></div>
    <div v-if="state.receipt" class="receipt-panel" role="status"><p class="eyebrow gold">REQUEST RECEIVED</p><h2>Thank you. We’ll take it from here.</h2><p class="request-number">{{ state.receipt.request_no }}</p><p>Your representative will review your request. Shipping and any additional charges will be included in a proposal for your confirmation before a formal PI is issued.</p><div class="checkout-actions"><button class="button primary" @click="emit('order', state.receipt.request_id)">View request</button><button class="button secondary" @click="emit('collection')">Back to collection</button></div></div>
    <section v-else-if="pending" class="recovery-panel" aria-live="polite">
      <p class="eyebrow gold">REQUEST STATUS</p><h2>{{ state.submission.status === 'submitting' ? 'Sending your request…' : state.submission.status === 'checking' ? 'Checking your request…' : 'Let’s confirm the result.' }}</h2>
      <p v-if="state.submission.status === 'uncertain'">The connection did not confirm whether your request was received. Check the original request before placing another one.</p>
      <p v-else>Please keep this page open. Your selection is protected while we confirm the result.</p>
      <p class="small muted recovery-reference">Reference: {{ state.submission.key }}</p>
      <p v-if="!state.submission.refreshRecovery" class="small">This browser cannot save the recovery reference. Keep this page open or save the reference above for your representative.</p>
      <div v-if="state.submission.status === 'uncertain'" class="checkout-actions"><button class="button primary" @click="act(() => submission.recover())">Check request status</button><button v-if="state.submission.canRetry" class="button secondary" @click="act(() => submission.retry())">Retry original request</button></div>
      <p v-if="state.submission.status === 'uncertain' && !state.submission.canRetry" class="small muted">After a refresh, only a status check is available. If it remains unresolved, share the reference with your representative.</p>
    </section>
    <div v-else-if="browsingOnly" class="empty-state"><span class="empty-symbol" aria-hidden="true">◇</span><h2>Collection access only.</h2><p>Your access is for browsing. Contact your representative to request ordering access.</p><button class="button primary" @click="emit('collection')">Explore your collection</button></div>
    <div v-else-if="!state.lines.length" class="empty-state"><span class="empty-symbol" aria-hidden="true">◇</span><h2>A new beginning.</h2><p>Add your approved products to start a request.</p><button class="button primary" @click="emit('collection')">Explore your collection</button></div>
    <div v-else class="checkout-layout">
      <div class="checkout-draft">
        <section v-if="state.quote?.reorder" class="checkout-card reorder-comparison"><p class="eyebrow gold">A FRESH REVIEW</p><h2>Since your previous request</h2><p class="small muted">These are current product terms. Check the copied delivery details, enter a new PO if needed, and review shipping separately with your representative.</p><ProposalDiff :changes="{ items: state.quote.reorder.changes, fields: [] }" /></section>
        <section class="checkout-card"><header><span class="step-mark">01</span><div><h2>The selection</h2><p class="small muted">Displayed prices are provisional until server review. Stock is not reserved.</p></div></header>
          <article v-for="line in state.lines" :key="line.item_id" class="cart-line"><div class="cart-monogram" aria-hidden="true">Ls</div><div class="cart-description"><p class="small gold">{{ line.customer_sku }}</p><h3>{{ line.model_name }}</h3><p class="small muted">{{ line.color_name }} · {{ line.length_display }} · {{ line.weight_display }}</p><p class="small">{{ unitPrice(line.unit_price) }} / {{ line.sale_unit }}</p><p v-if="line.unavailable" class="alert error small" role="status">No longer available. Remove this item to continue; your other products and delivery details are kept.</p></div><div class="cart-controls"><label :for="`qty-${line.item_id}`" class="small">Quantity</label><input :id="`qty-${line.item_id}`" type="number" inputmode="numeric" :min="minimumQuantity(line)" :step="line.step_qty" max="10000" :value="line.quantity" :disabled="line.unavailable" @change="quantity(line, $event)" /><button class="text-button small" :aria-label="`Remove ${line.model_name}`" @click="act(() => checkout.remove(line.item_id))">Remove</button></div></article>
        </section>
        <form class="checkout-card delivery-form" @submit.prevent="getQuote">
          <header><span class="step-mark">02</span><div><h2>The details</h2><p class="small muted">Your delivery details are kept only in this session until you request a server review.</p></div></header>
          <div class="delivery-grid"><label v-for="[field, label, autocomplete, max, required] in fields" :key="field" :class="{ 'wide-field': field.startsWith('address_') }"><span>{{ label }}</span><input :value="state.delivery[field]" :autocomplete="autocomplete" :maxlength="max" :required="required" :type="field === 'phone' ? 'tel' : 'text'" :pattern="field === 'country_code' ? '[A-Za-z]{2}' : undefined" :minlength="field === 'phone' ? 3 : undefined" @input="act(() => checkout.delivery(field, $event.target.value))" /></label>
            <label class="wide-field"><span>Your PO / reference (optional)</span><input :value="state.customer_po" maxlength="80" @input="act(() => checkout.details('customer_po', $event.target.value))" /></label>
            <label class="wide-field"><span>Request notes (optional)</span><textarea :value="state.remark" maxlength="1000" rows="3" @input="act(() => checkout.details('remark', $event.target.value))"></textarea></label>
          </div>
          <button class="button primary full" :disabled="state.quoting" type="submit">{{ state.quoting ? 'Reviewing availability and pricing…' : state.quote ? 'Refresh server review' : 'Review request' }}</button>
        </form>
      </div>
      <aside ref="review" class="checkout-review checkout-card" tabindex="-1" aria-label="Server review"><p class="eyebrow gold">03 / REVIEW & REQUEST</p><h2>Every detail, confirmed.</h2>
        <template v-if="state.quote">
          <p class="small muted">Current product names, pricing and delivery details returned by the server. Review any changes before submitting.</p>
          <ul class="quote-lines"><li v-for="line in state.quote.items" :key="line.line_key"><div><strong>{{ line.display_snapshot.model_name }}</strong><small>{{ line.display_snapshot.color_name }} · {{ line.display_snapshot.customer_sku }}<br /><span v-if="line.display_snapshot.length">Length: {{ line.display_snapshot.length }}<br /></span><span v-if="line.display_snapshot.weight">Weight: {{ line.display_snapshot.weight }}<br /></span>{{ line.quantity }} {{ line.display_snapshot.unit }} × {{ unitPrice(line.unit_price) }}</small></div><span>{{ money(line.line_amount) }}</span><small v-if="changedLine(line)" class="gold">Updated since selection. Please review this line.</small><small v-if="line.discount_amount !== '0.00'">Line discount: {{ money(line.discount_amount) }}</small></li></ul>
          <dl class="quote-totals"><div><dt>Product subtotal</dt><dd>{{ money(state.quote.product_amount) }}</dd></div><div><dt>Shipping & other charges</dt><dd>Pending review</dd></div><div><dt>Final total</dt><dd>To be confirmed</dd></div></dl>
          <div class="quote-address"><h3>Deliver to</h3><p>{{ state.quote.delivery.contact_name }} · {{ state.quote.delivery.phone }}<br />{{ state.quote.delivery.address_line1 }}<br v-if="state.quote.delivery.address_line2" />{{ state.quote.delivery.address_line2 }}<br />{{ [state.quote.delivery.city, state.quote.delivery.region, state.quote.delivery.postal_code, state.quote.delivery.country_code].filter(Boolean).join(', ') }}</p><p v-if="state.quote.customer_po">PO: {{ state.quote.customer_po }}</p><p v-if="state.quote.remark">Notes: {{ state.quote.remark }}</p><p v-if="state.quote.payment_terms_snapshot?.display_text">Payment terms: {{ state.quote.payment_terms_snapshot.display_text }}</p></div>
          <p class="small muted">Review valid until {{ beijingTime(state.quote.expires_at) }}. Availability will be checked again on submission.</p>
          <p v-if="expired" class="alert error" role="status">This review has expired. Refresh it to continue.</p>
          <label class="quote-confirmation"><input type="checkbox" :checked="state.acknowledged" @change="act(() => checkout.acknowledge($event.target.checked))" /><span>I confirm these products and delivery details. I understand this request does not reserve stock and that final charges require my confirmation.</span></label>
          <button class="button primary full" :disabled="expired || !state.acknowledged" @click="act(() => checkout.submit())">Submit order request</button>
        </template>
        <template v-else><p class="muted">Complete your delivery details to review current pricing and availability.</p><div class="review-placeholder"><span aria-hidden="true">◇</span><p>Prepared for you.<br />Confirmed by your representative.</p></div><p class="small muted">Shipping, packaging and additional charges will be confirmed in a proposal. A formal PI follows your confirmation and your representative’s approval.</p></template>
      </aside>
    </div>
  </section>
</template>
