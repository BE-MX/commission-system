<script setup>
import { computed, nextTick, onBeforeUnmount, ref, toRaw, watch } from 'vue'
import { beijingTime, money } from '../presentation.mjs'
import { quoteDeadline } from '../state/checkout.mjs'
import { currentProposal } from '../state/orderDecision.mjs'
import { orderStatuses, statusLabel, totalLabel, eventLabel, piLabel } from '../orderPresentation.mjs'
import OrderTerms from './OrderTerms.vue'
import ProposalDiff from './ProposalDiff.vue'
import ReorderDialog from './ReorderDialog.vue'
const props = defineProps({ api: { type: Object, required: true }, session: { type: Object, required: true }, requestId: { type: String, default: '' }, decision: { type: Object, required: true }, decisionState: { type: Object, required: true }, checkout: { type: Object, required: true }, checkoutState: { type: Object, required: true } })
const emit = defineEmits(['open', 'list', 'checkout'])
const status = ref(''), page = ref(1), listing = ref(null), order = ref(null), busy = ref(false), error = ref(null)
const dialog = ref(null), actionOrder = ref(null), action = ref(''), reason = ref(''), accepted = ref(false), actionError = ref(null), downloading = ref(false), errorSummary = ref(null), clock = ref(Date.now())
let active = true, sequence = 0, controller, opener
const objectUrls = new Set(), timers = new Set()
const timer = setInterval(() => { clock.value = Date.now() }, 1000)
const pending = computed(() => ['sending', 'checking', 'uncertain'].includes(props.decisionState.status))
const proposal = computed(() => order.value && currentProposal(order.value))
const expired = computed(() => proposal.value && (proposal.value.expired || !(quoteDeadline(proposal.value.expires_at) > clock.value)))
const can = value => Boolean(order.value?.available_actions?.includes(value))
const actionNames = { cancel: 'Cancel request', accept_proposal: 'Accept proposal', reject_proposal: 'Request changes', accept_pi: 'Accept PI update', reject_pi: 'Decline PI update' }
const actionIsAccept = computed(() => action.value.startsWith('accept'))
const pageCount = computed(() => Math.max(1, Math.ceil((listing.value?.total || 0) / 20)))
async function load() {
  const current = ++sequence
  controller?.abort(); controller = new AbortController()
  busy.value = true; error.value = null; order.value = null; listing.value = null
  try {
    const data = props.requestId ? await props.api.order(props.requestId, controller.signal) : await props.api.orders({ status: status.value, page: page.value, page_size: 20 }, controller.signal)
    if (active && current === sequence) { if (props.requestId) order.value = data; else listing.value = data }
  } catch (problem) { if (active && current === sequence && !['STALE_SCOPE', 'REQUEST_ABORTED'].includes(problem.code)) error.value = problem }
  finally { if (active && current === sequence) busy.value = false }
}
watch(() => props.requestId, () => { dialog.value?.close(); load() }, { immediate: true })
watch(() => props.decisionState.status, value => { if (['confirmed', 'failed'].includes(value)) load() })
watch(error, async value => { if (value) { await nextTick(); errorSummary.value?.focus() } })
function filter() { page.value = 1; load() }
async function ask(value, event) {
  if (pending.value || !can(value)) return
  action.value = value; actionOrder.value = structuredClone(toRaw(order.value)); opener = event.currentTarget
  reason.value = ''; accepted.value = false; actionError.value = null
  await nextTick(); dialog.value.showModal()
}
function closed() {
  actionOrder.value = null; reason.value = ''; accepted.value = false
  if (active && opener?.isConnected) {
    opener.focus()
    opener.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'instant' })
  }
}
async function execute() {
  if (actionIsAccept.value && !accepted.value) return
  try {
    // begin freezes the command synchronously, before modal teardown or navigation.
    const result = props.decision.begin(actionOrder.value, action.value, reason.value)
    dialog.value.close()
    await result
  } catch (problem) { if (active && problem.code !== 'STALE_SCOPE') { if (dialog.value?.open) actionError.value = problem; else error.value = problem } }
}
async function recovery(retry) {
  try { await (retry ? props.decision.retry() : props.decision.recover()) }
  catch (problem) { if (active && problem.code !== 'STALE_SCOPE') error.value = problem }
}
async function download() {
  if (downloading.value || !can('download_pi')) return
  downloading.value = true; error.value = null
  try {
    const id = order.value.request_id, started = sequence, startedScope = props.api.scopeVersion
    const blob = await props.api.download(id)
    // The client may resolve before a session-clear microtask, while Vue has not unmounted us yet.
    if (!active || started !== sequence || startedScope !== props.api.scopeVersion) return
    const url = URL.createObjectURL(blob); objectUrls.add(url)
    const link = document.createElement('a')
    link.href = url; link.download = `LeShine-PI-${id}.pdf`; link.click()
    const timerId = setTimeout(() => { URL.revokeObjectURL(url); objectUrls.delete(url); timers.delete(timerId) }, 30000)
    timers.add(timerId)
  } catch (problem) {
    if (active && problem.code !== 'STALE_SCOPE') { await load(); if (active) error.value = problem }
  } finally { if (active) downloading.value = false }
}
onBeforeUnmount(() => {
  active = false; sequence++; controller?.abort(); dialog.value?.close(); clearInterval(timer)
  timers.forEach(clearTimeout); objectUrls.forEach(url => URL.revokeObjectURL(url))
})
</script>

<template>
  <section class="collection-page orders-page">
    <header class="collection-heading"><div><p class="eyebrow gold">YOUR PARTNERSHIP, IN PROGRESS</p><h1>{{ requestId ? 'Your order request.' : 'Your requests.' }}</h1><p v-if="order" class="request-number small">Reference: {{ order.request_no }}</p><p class="muted">Every request, every detail, in one place.</p></div><button v-if="requestId" class="text-button" @click="emit('list')">← All requests</button></header>
    <section v-if="pending" class="order-command-notice" aria-live="polite"><h2>{{ decisionState.status === 'sending' ? 'Recording your decision…' : decisionState.status === 'checking' ? 'Checking original action receipt…' : 'The action result needs confirmation.' }}</h2><p>{{ decisionState.operation.request_no || decisionState.operation.request_id }} · {{ actionNames[decisionState.operation.action] }}</p><p v-if="decisionState.status === 'uncertain'">We could not verify the original action receipt. Check its reference with the server. A current request status alone cannot confirm this action.</p><p v-if="decisionState.latest">Latest request status: {{ statusLabel(decisionState.latest.status) }}<span v-if="decisionState.latest.pi_amendment"> · {{ piLabel(decisionState.latest.pi_amendment.status) }}</span></p><div v-if="decisionState.status === 'uncertain'" class="checkout-actions"><button class="button secondary" @click="recovery(false)">Check original action receipt</button><button v-if="decisionState.canRetry" class="button primary" @click="recovery(true)">Retry original action</button></div><p class="small muted">{{ decisionState.refreshRecovery ? 'A query reference is saved for refresh in this tab. After refresh, only the original receipt can be checked; the action will not be resent.' : 'This browser could not save a refresh reference. Keep this page open and check the original receipt before continuing.' }}</p></section>
    <div v-if="decisionState.status === 'confirmed' && decisionState.operation.request_id === requestId" class="session-notice" role="status">Original action on {{ decisionState.operation.request_no || decisionState.operation.request_id }} was recorded. Request status when checked: {{ statusLabel(decisionState.receipt.current_state) }}. Refresh details to view the latest request.</div>
    <div v-if="decisionState.status === 'failed' && decisionState.operation.request_id === requestId" class="alert error" role="alert">{{ decisionState.error.message }} Please review the refreshed request before continuing.</div>
    <div v-if="error" ref="errorSummary" class="alert error" role="alert" tabindex="-1"><p>{{ error.message }}</p><small v-if="error.traceId">Reference: {{ error.traceId }}</small><button class="text-button" @click="load">Reload current request</button></div>
    <form v-if="!requestId" class="orders-toolbar" @submit.prevent="filter"><label><span>Request status</span><select v-model="status" @change="filter"><option value="">All requests</option><option v-for="(label, value) in orderStatuses" :key="value" :value="value">{{ label }}</option></select></label><button class="button secondary" :disabled="busy" @click="load" type="button">Refresh</button></form>
    <div v-if="busy" class="empty-state" role="status">Loading your {{ requestId ? 'request' : 'requests' }}…</div>
    <template v-else-if="!requestId && listing"><div v-if="!listing.items.length" class="empty-state"><h2>{{ status ? 'No requests with this status.' : 'Your next chapter starts here.' }}</h2><p>{{ status ? 'Try another status to find your request.' : 'Submitted requests will appear here.' }}</p></div><div v-else class="order-list"><article v-for="item in listing.items" :key="item.request_id" class="order-list-item"><div><span :class="['order-badge', item.status]">{{ statusLabel(item.status) }}</span><h2><a :href="`/orders/${item.request_id}`" @click.prevent="emit('open', item.request_id)">{{ item.request_no }} <span aria-hidden="true">↗</span></a></h2><p class="small muted">{{ beijingTime(item.submitted_at) }}<span v-if="item.customer_po"> · PO {{ item.customer_po }}</span></p></div><div v-if="session.capabilities.view_price" class="order-list-amount"><strong>{{ money(item.total_amount ?? item.product_amount) }}</strong><small>{{ totalLabel(item) }}</small></div></article></div><nav v-if="pageCount > 1" class="pagination" aria-label="Request pages"><button class="button secondary" :disabled="page <= 1" @click="page--; load()">← Previous</button><span>Page {{ page }} of {{ pageCount }}</span><button class="button secondary" :disabled="page >= pageCount" @click="page++; load()">Next →</button></nav></template>
    <template v-else-if="order">
      <div class="order-summary-bar"><span :class="['order-badge', order.status]">{{ statusLabel(order.status) }}</span><span class="small muted">Submitted {{ beijingTime(order.submitted_at) }}</span><button class="text-button" @click="load">Refresh details</button></div>
      <section v-if="order.status === 'invoice_created'" class="pi-panel"><div><p class="eyebrow gold">PROFORMA INVOICE</p><h2>{{ piLabel(order.pi_amendment?.status) }}</h2><p class="small muted">Only the current confirmed and published version is available. A PI does not reserve stock or confirm payment.</p></div><button v-if="can('download_pi')" class="button primary" :disabled="downloading" @click="download">{{ downloading ? 'Preparing your PDF…' : 'Download confirmed PI' }}</button></section>
      <section class="checkout-card order-document"><h2>{{ order.status === 'invoice_created' ? 'Last published request details' : proposal ? 'Proposed request details' : 'Request details' }}</h2><OrderTerms :document="order" :show-price="session.capabilities.view_price" /></section>
      <section v-if="proposal && session.capabilities.view_price" class="checkout-card proposal-panel"><p class="eyebrow gold">{{ order.status === 'invoice_created' ? 'PI UPDATE' : 'PROPOSAL' }}</p><h2>{{ expired ? 'This proposal has expired.' : 'Review the details before confirming.' }}</h2><p class="small muted">Valid until {{ beijingTime(proposal.expires_at) }}. {{ order.status === 'invoice_created' ? 'Acceptance allows your representative to publish this update to the existing PI.' : 'Acceptance sends this proposal for your representative’s final approval.' }}</p><ProposalDiff :changes="proposal.changes" /><OrderTerms v-if="order.status === 'invoice_created'" :document="proposal" show-price /><div class="checkout-actions"><button v-if="can('accept_proposal') || can('accept_pi')" class="button primary" :disabled="pending || expired" @click="ask(order.status === 'invoice_created' ? 'accept_pi' : 'accept_proposal', $event)">{{ order.status === 'invoice_created' ? 'Review and accept PI update' : 'Review and accept proposal' }}</button><button v-if="can('reject_proposal') || can('reject_pi')" class="button secondary" :disabled="pending" @click="ask(order.status === 'invoice_created' ? 'reject_pi' : 'reject_proposal', $event)">{{ order.status === 'invoice_created' ? 'Decline PI update' : 'Request changes' }}</button></div></section>
      <section class="order-timeline"><h2>Request history</h2><ol><li v-for="(event, index) in order.customer_safe_timeline" :key="index"><span>{{ eventLabel(event.event) }}</span><time>{{ beijingTime(event.at) }}</time></li></ol></section>
      <div class="order-secondary-actions"><ReorderDialog v-if="session.capabilities.place_order && session.capabilities.view_price" :order="order" :checkout="checkout" :checkout-state="checkoutState" :disabled="pending" @ready="emit('checkout')" /><button v-if="can('cancel')" class="text-button" :disabled="pending" @click="ask('cancel', $event)">Cancel this request</button></div>
    </template>
    <dialog ref="dialog" class="product-dialog decision-dialog" aria-label="Confirm request action" @close="closed"><template v-if="actionOrder"><header><p class="eyebrow gold">{{ actionOrder.request_no }}</p><button class="icon-button" aria-label="Close confirmation" @click="dialog.close()">×</button></header><form @submit.prevent="execute"><div class="dialog-body"><h2>{{ actionNames[action] }}</h2><template v-if="actionIsAccept"><p>Total: <strong>{{ money(action === 'accept_pi' ? actionOrder.pi_amendment.proposal.total_amount : actionOrder.total_amount) }}</strong></p><p>Your representative will {{ action === 'accept_pi' ? 'publish the accepted update to your existing PI' : 'review your acceptance before issuing the formal PI' }}.</p><label class="quote-confirmation"><input v-model="accepted" type="checkbox" required /><span>I have reviewed the products, specifications, complete charges, delivery details and payment terms, and accept this version.</span></label></template><label v-else class="reason-field"><span>{{ action === 'cancel' ? 'Reason for cancelling' : 'What would you like to change?' }}</span><textarea v-model="reason" rows="4" maxlength="500" required></textarea></label><div v-if="actionError" class="alert error" role="alert">{{ actionError.message }}</div></div><footer><button class="button secondary" type="button" @click="dialog.close()">Go back</button><button class="button primary" :disabled="pending || (actionIsAccept ? !accepted : !reason.trim())" type="submit">{{ actionNames[action] }}</button></footer></form></template></dialog>
  </section>
</template>
