<script setup>
import SalesContact from './components/SalesContact.vue'
import { onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import { createPortalClient } from './api/client.mjs'
import { browserChannel } from './state/browserChannel.mjs'
import BrandMark from './components/BrandMark.vue'
import LoginView from './components/LoginView.vue'
import CollectionView from './components/CollectionView.vue'
import CheckoutView from './components/CheckoutView.vue'
import { createSubmission } from './state/submission.mjs'
import { createCheckout } from './state/checkout.mjs'
import { createOrderDecision } from './state/orderDecision.mjs'
import OrdersView from './components/OrdersView.vue'

const props = defineProps({ invitation: { type: String, default: '' } })
const session = shallowRef(null), stage = ref('restoring'), error = ref(null), signingOut = ref(false)
const notice = ref(''), invitation = ref(props.invitation), recoveryError = shallowRef(null), decisionRecoveryError = shallowRef(null)
const channelNotice = ref('')
const channel = browserChannel(window, () => { channelNotice.value = 'This browser cannot synchronize sessions across tabs. Use one tab and sign out when finished.' })
const api = createPortalClient({ channel })
let storage = null
try { storage = window.sessionStorage } catch { /* Recovery remains available in memory. */ }
const submission = createSubmission({ api, storage })
const checkout = createCheckout({ api, submission })
const decision = createOrderDecision({ api, storage }), decisionState = shallowRef(decision.state)
const offDecision = decision.subscribe(value => { decisionState.value = value })
const checkoutState = shallowRef(checkout.state), route = ref('collection')
const offCheckout = checkout.subscribe(value => { checkoutState.value = value })
function navigate(destination, replace = false) {
  route.value = destination
  history[replace ? 'replaceState' : 'pushState'](null, '', '/' + destination)
}
function pathRoute() {
  const path = location.pathname.slice(1)
  if (path === 'cart') return 'checkout'
  if (['checkout', 'collection', 'orders'].includes(path) || /^orders\/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}(\/proposal)?$/i.test(path)) return path
  return 'collection'
}
function back() { route.value = pathRoute() }
window.addEventListener('popstate', back)
function restoreSubmission() {
  recoveryError.value = null
  try { return submission.restorePending() }
  catch (problem) { recoveryError.value = problem; return false }
}
function restoreDecision() {
  decisionRecoveryError.value = null
  try { return decision.restorePending() }
  catch (problem) { decisionRecoveryError.value = problem; return false }
}
function checkActionReference() {
  if (restoreDecision()) navigate('orders/' + decision.state.operation.request_id)
}
function checkRecoveryReference() {
  if (restoreSubmission()) navigate('checkout')
}
const unsubscribe = api.subscribe(event => {
  const wasAuthenticated = Boolean(session.value)
  session.value = event.session
  if (event.session) {
    stage.value = 'collection'; error.value = null; invitation.value = ''; notice.value = ''
    const recovering = restoreSubmission(), recoveringAction = restoreDecision()
    navigate(recovering ? 'checkout' : recoveringAction ? 'orders/' + decision.state.operation.request_id : pathRoute(), true)
  } else if (!['restoring'].includes(event.reason)) {
    recoveryError.value = null; decisionRecoveryError.value = null
    stage.value = event.reason === 'signing-out' ? 'signing-out' : 'login'
    if (event.reason === 'another-tab') notice.value = 'Your session changed in another tab. Sign in again to continue.'
    if (event.reason === 'expired' && wasAuthenticated) notice.value = 'Your session has expired. Sign in again to continue.'
  }
})
async function restore() {
  stage.value = 'restoring'; error.value = null
  try { await api.restore() }
  catch (problem) {
    if (problem.code === 'STALE_SCOPE') return
    if (problem.status === 401) stage.value = 'login'
    else { error.value = problem; stage.value = 'unavailable' }
  }
}
async function logout() {
  if (signingOut.value) return
  signingOut.value = true; error.value = null; notice.value = ''
  try { await api.logout(); stage.value = 'login'; history.replaceState(null, '', '/login') }
  catch (problem) { if (problem.code !== 'STALE_SCOPE') { error.value = problem; stage.value = problem.status === 401 ? 'login' : 'logout-failed' } }
  finally { signingOut.value = false }
}
onMounted(() => { if (invitation.value) stage.value = 'login'; else restore() })
onBeforeUnmount(() => { window.removeEventListener('popstate', back); unsubscribe(); offCheckout(); offDecision(); checkout.dispose(); submission.dispose(); decision.dispose(); api.dispose() })
</script>

<template>
  <a class="skip-link" href="#main-content">Skip to content</a>
  <div v-if="notice" class="session-notice" role="status">{{ notice }}</div>
  <div v-if="channelNotice" class="session-notice" role="status">{{ channelNotice }}</div>
  <div v-if="stage === 'restoring' || stage === 'signing-out'" id="main-content" class="gate-state" role="status"><BrandMark /><p>{{ stage === 'signing-out' ? 'Signing out…' : 'Opening your private collection…' }}</p></div>
  <div v-else-if="stage === 'unavailable' || stage === 'logout-failed'" id="main-content" class="gate-state"><BrandMark /><p class="eyebrow gold">PARTNER ACCESS</p><h1>{{ stage === 'logout-failed' ? 'Sign-out needs another try.' : 'We’ll be right with you.' }}</h1><p>{{ stage === 'logout-failed' ? 'Your private view is cleared, but we could not confirm sign-out with the server.' : 'Your collection is temporarily unavailable. Please try again shortly.' }}</p><p v-if="error" class="small muted">{{ error.message }}</p><button class="button primary" :disabled="signingOut" @click="stage === 'logout-failed' ? logout() : restore()">{{ signingOut ? 'Signing out…' : 'Try again' }}</button></div>
  <LoginView v-else-if="!session" id="main-content" :api="api" :invitation="invitation" />
  <div v-else class="portal-shell">
    <header class="portal-header"><a href="/collection" class="brand-link" aria-label="LeShine collection" @click.prevent="navigate('collection')"><BrandMark /></a><nav aria-label="Main navigation"><a href="/collection" :aria-current="route === 'collection' ? 'page' : undefined" @click.prevent="navigate('collection')">Collection</a><a v-if="session.capabilities.place_order" href="/checkout" :aria-current="route === 'checkout' ? 'page' : undefined" @click.prevent="navigate('checkout')">Selection <span class="nav-count">{{ checkoutState.lines.length }}</span></a><a href="/orders" :aria-current="route.startsWith('orders') ? 'page' : undefined" @click.prevent="navigate('orders')">Requests</a></nav><div class="account-menu"><span>{{ session.me.company_display_name }}<small>Private partner access</small></span><button class="text-button" :disabled="signingOut" @click="logout">{{ signingOut ? 'Signing out…' : 'Sign out' }}</button></div></header>
    <div v-if="recoveryError" class="session-notice" role="alert"><p>{{ recoveryError.message }}</p><button class="text-button" @click="checkRecoveryReference">Check recovery reference</button> <button class="text-button" @click="navigate('orders')">View existing requests</button></div>
    <div v-if="decisionRecoveryError" class="session-notice" role="alert"><p>{{ decisionRecoveryError.message }}</p><button class="text-button" @click="checkActionReference">Check action reference</button> <button class="text-button" @click="navigate('orders')">View existing requests</button></div>
    <div v-if="route !== 'checkout' && ['uncertain', 'submitting', 'checking'].includes(checkoutState.submission.status)" class="session-notice" role="status">Your previous request needs confirmation. <button class="text-button" @click="navigate('checkout')">View request status</button></div>
    <div v-if="!route.startsWith('orders') && ['sending', 'checking', 'uncertain'].includes(decisionState.status)" class="session-notice" role="status">Your request action needs confirmation. <button class="text-button" @click="navigate('orders/' + decisionState.operation.request_id)">View action status</button></div>
    <main id="main-content"><CollectionView v-if="route === 'collection'" :key="api.scopeVersion" :api="api" :session="session" :checkout="checkout" @checkout="navigate('checkout')" /><CheckoutView v-else-if="route === 'checkout'" :key="api.scopeVersion" :checkout="checkout" :state="checkoutState" :submission="submission" :ordering-enabled="session.capabilities.place_order" @collection="navigate('collection')" @order="id => navigate('orders/' + id)" /><OrdersView v-else :key="api.scopeVersion" :api="api" :session="session" :request-id="route.split('/')[1] || ''" :decision="decision" :decision-state="decisionState" :checkout="checkout" :checkout-state="checkoutState" @checkout="navigate('checkout')" @open="id => navigate('orders/' + id)" @list="navigate('orders')" /></main>
    <footer class="portal-footer"><span>LESHINE · MADE FOR YOUR NEXT CHAPTER</span><SalesContact :key="api.scopeVersion" :api="api" /><span>Partner collection / Powered by Ark</span></footer>
  </div>
</template>
