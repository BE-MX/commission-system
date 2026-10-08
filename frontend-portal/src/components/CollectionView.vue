<script setup>
import ProductImage from './ProductImage.vue'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { unitPrice as price, beijingTime } from '../presentation.mjs'
import { minimumQuantity } from '../state/checkout.mjs'
const props = defineProps({ api: { type: Object, required: true }, session: { type: Object, required: true }, checkout: { type: Object, required: true } })
const emit = defineEmits(['checkout'])
const quantity = ref(1), quantityInput = ref(null), addErrorSummary = ref(null), addError = ref(null), added = ref(false)
const quantityInvalid = computed(() => addError.value?.code === 'INVALID_QUANTITY')
const keyword = ref(''), category = ref(''), inStock = ref(false), sort = ref('curated'), page = ref(1)
const result = ref(null), busy = ref(true), error = ref(null), selected = ref(null), dialog = ref(null)
let controller, sequence = 0, debounce, opener
const pageCount = computed(() => Math.max(1, Math.ceil((result.value?.total || 0) / 24)))
const availability = value => ({ available: 'Available to request', unavailable: 'Currently unavailable', unknown: 'Availability pending' })[value] || 'Availability pending'

async function load() {
  const current = ++sequence
  controller?.abort(); controller = new AbortController()
  busy.value = true; error.value = null; result.value = null
  try {
    const data = await props.api.catalog({ keyword: keyword.value, category: category.value,
      in_stock_only: inStock.value, sort: sort.value, page: page.value, page_size: 24 }, controller.signal)
    if (current === sequence) result.value = data
  } catch (problem) { if (current === sequence && !['STALE_SCOPE', 'REQUEST_ABORTED'].includes(problem.code)) error.value = problem }
  finally { if (current === sequence) busy.value = false }
}
function changed() { page.value = 1; clearTimeout(debounce); load() }
watch(keyword, () => {
  controller?.abort(); sequence++; busy.value = true; result.value = null
  clearTimeout(debounce); debounce = setTimeout(changed, 250)
})
async function show(item, event) {
  selected.value = item; opener = event.currentTarget; quantity.value = minimumQuantity(item); addError.value = null; added.value = false
  await nextTick()
  dialog.value?.showModal()
}
function close() { dialog.value.close() }
function closed() { selected.value = null; opener?.focus() }
async function add() {
  addError.value = null
  try { props.checkout.add(selected.value, quantity.value); added.value = true }
  catch (problem) {
    addError.value = problem
    await nextTick()
    if (!dialog.value?.open) return
    if (quantityInvalid.value) quantityInput.value?.focus()
    else addErrorSummary.value?.focus()
  }
}
onMounted(load)
onBeforeUnmount(() => { sequence++; controller?.abort(); clearTimeout(debounce); dialog.value?.close() })
</script>

<template>
  <section class="collection-page">
    <header class="collection-heading"><div><p class="eyebrow gold">CURATED FOR {{ session.me.company_display_name }}</p><h1>Your next signature.</h1><p class="muted">Explore your collection, in the names and shades you know.</p></div><span class="collection-stamp">LESHINE<br /><small>PARTNER COLLECTION</small></span></header>
    <div class="collection-message"><span class="status-dot" aria-hidden="true"></span><span v-if="session.capabilities.place_order">Requests are reviewed by your representative. Availability is confirmed before your PI is issued.</span><span v-else>Your access is for browsing. Contact your representative to request ordering access.</span></div>
    <form class="collection-toolbar" role="search" @submit.prevent="changed">
      <label class="search-field"><span class="sr-only">Search your collection</span><span aria-hidden="true">⌕</span><input v-model="keyword" type="search" placeholder="Search model, shade or your SKU" maxlength="100" /></label>
      <label><span class="sr-only">Product category</span><select v-model="category" @change="changed"><option value="">All products</option><option value="hair">Hair collection</option><option value="accessory">Accessories</option></select></label>
      <label class="check-filter"><input v-model="inStock" type="checkbox" @change="changed" /> Available only</label>
      <label><span class="sr-only">Sort products</span><select v-model="sort" @change="changed"><option value="curated">Curated order</option><option value="name">Name A–Z</option></select></label>
    </form>
    <div class="collection-results" aria-live="polite"><span>{{ busy ? 'Loading your collection…' : error ? 'Collection unavailable' : `${result?.total || 0} products in your collection` }}</span><span v-if="session.capabilities.view_price" class="small muted">Your pricing · USD</span></div>
    <div v-if="error" class="empty-state" role="alert"><h2>We couldn’t load your collection.</h2><p>{{ error.message }}</p><button class="button primary" @click="load">Try again</button><small v-if="error.traceId">Reference: {{ error.traceId }}</small></div>
    <div v-else-if="busy" class="product-grid" aria-hidden="true"><div v-for="n in 6" :key="n" class="product-skeleton"><div></div><span></span><span></span></div></div>
    <div v-else-if="!result?.items?.length" class="empty-state"><span class="empty-symbol" aria-hidden="true">◇</span><h2>{{ keyword || category || inStock ? 'No matches just yet.' : 'Your collection is being prepared.' }}</h2><p>{{ keyword || category || inStock ? 'Try another model or shade, or adjust your filters.' : 'Your representative will make your approved products available here.' }}</p><button v-if="keyword || category || inStock" class="button secondary" @click="keyword = ''; category = ''; inStock = false; changed()">Clear filters</button></div>
    <div v-else class="product-grid">
      <article v-for="item in result.items" :key="item.item_id" class="product-card">
        <button class="product-open" @click="show(item, $event)" :aria-label="`View ${item.model_name}, ${item.color_name}`">
          <div class="product-art"><span class="product-kind">{{ item.category === 'hair' ? 'HAIR COLLECTION' : 'ACCESSORIES' }}</span><ProductImage :url="item.image_url" :alt="`${item.model_name}, ${item.color_name}`" /><span class="product-art-label">{{ item.color_name }}</span></div>
          <div class="product-caption"><div class="product-line"><span class="small muted">{{ item.customer_sku || 'YOUR COLLECTION' }}</span><span aria-hidden="true">↗</span></div><h2>{{ item.model_name }}</h2><p class="muted">{{ item.color_name }}<span v-if="item.length_display"> · {{ item.length_display }}</span><span v-if="item.weight_display"> · {{ item.weight_display }}</span></p><div class="product-bottom"><strong v-if="session.capabilities.view_price">{{ price(item.unit_price) }}<small v-if="item.unit_price != null"> / {{ item.sale_unit }}</small></strong><span :class="['stock-state', item.availability]"><span aria-hidden="true">●</span> {{ availability(item.availability) }}</span></div><p v-if="item.inventory_observed_at" class="small muted">Stock checked {{ beijingTime(item.inventory_observed_at) }}</p></div>
        </button>
      </article>
    </div>
    <nav v-if="result && pageCount > 1" class="pagination" aria-label="Collection pages"><button class="button secondary" :disabled="page <= 1 || busy" @click="page--; load()">← Previous</button><span>Page {{ page }} of {{ pageCount }}</span><button class="button secondary" :disabled="page >= pageCount || busy" @click="page++; load()">Next →</button></nav>
    <dialog ref="dialog" class="product-dialog" aria-labelledby="product-title" @close="closed" @click="event => { if (event.target === dialog) close() }">
      <template v-if="selected"><header><p class="eyebrow gold">YOUR COLLECTION</p><button class="icon-button" aria-label="Close product" @click="close">×</button></header><div class="dialog-body" role="region" aria-label="Product specifications" tabindex="0"><h2 id="product-title">{{ selected.model_name }}</h2><p class="muted">{{ selected.color_name }}</p><dl class="product-specs"><div v-if="selected.customer_sku"><dt>Your SKU</dt><dd>{{ selected.customer_sku }}</dd></div><div v-if="selected.length_display"><dt>Length</dt><dd>{{ selected.length_display }}</dd></div><div v-if="selected.weight_display"><dt>Weight</dt><dd>{{ selected.weight_display }}</dd></div><div><dt>Order unit</dt><dd>{{ selected.sale_unit }}</dd></div><div><dt>Minimum request</dt><dd>{{ selected.min_order_qty }} {{ selected.sale_unit }}</dd></div><div><dt>Quantity increment</dt><dd>{{ selected.step_qty }}</dd></div></dl><p v-if="session.capabilities.view_price" class="detail-price">{{ price(selected.unit_price) }}</p><p :class="['stock-state', selected.availability]">{{ availability(selected.availability) }}</p><p v-if="selected.inventory_observed_at" class="small muted">Stock checked {{ beijingTime(selected.inventory_observed_at) }}</p><p class="small muted">Availability is not a stock reservation. Final quantities and shipping are confirmed by your representative.</p></div><footer class="product-purchase"><template v-if="session.capabilities.place_order && selected.availability === 'available' && selected.unit_price != null && minimumQuantity(selected)"><label v-if="!added">Quantity<input ref="quantityInput" v-model="quantity" :aria-invalid="quantityInvalid ? 'true' : undefined" :aria-describedby="quantityInvalid ? 'product-add-error' : undefined" @input="addError = null" type="number" inputmode="numeric" :min="minimumQuantity(selected)" :step="selected.step_qty" max="10000" /></label><button v-if="!added" class="button primary" @click="add">Add to selection</button><template v-else><p role="status">Added to your selection.</p><button class="button primary" @click="close(); emit('checkout')">Review selection</button></template></template><button v-else class="button secondary" @click="close">Back to collection</button><p v-if="addError" id="product-add-error" ref="addErrorSummary" class="alert error" role="alert" tabindex="-1">{{ addError.message }}</p></footer></template>
    </dialog>
  </section>
</template>
