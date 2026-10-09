<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import OrderLine from './OrderLine.vue'
const props = defineProps({ order: { type: Object, required: true }, checkout: { type: Object, required: true }, checkoutState: { type: Object, required: true }, disabled: Boolean })
const emit = defineEmits(['ready'])
const dialog = ref(null), selected = ref([]), replace = ref(false), busy = ref(false), error = ref(null), errorSummary = ref(null)
let opener, attempt, generation = 0, active = true
const hasDraft = computed(() => props.checkoutState.lines.length > 0)
const blocked = computed(() => props.disabled || ['submitting', 'checking', 'uncertain'].includes(props.checkoutState.submission.status))
const unavailable = line => error.value?.issues?.some(issue => issue.line_key === line.line_key && issue.error_code === 'PRODUCT_UNAVAILABLE')
function invalidate() { generation++; attempt?.abort(); busy.value = false }
async function open(event) {
  if (blocked.value) return
  opener = event.currentTarget; selected.value = props.order.items.map(line => line.line_key); replace.value = false; error.value = null
  await nextTick(); dialog.value.showModal()
}
function close() { dialog.value.close() }
function closed() { invalidate(); selected.value = []; replace.value = false; error.value = null; opener?.focus() }
watch(() => props.order.request_id, () => dialog.value?.close())
watch(error, async value => { if (value) { await nextTick(); errorSummary.value?.focus() } })
async function prepare() {
  if (busy.value || blocked.value || !selected.value.length || (hasDraft.value && !replace.value)) return
  const current = ++generation
  attempt = new AbortController(); busy.value = true; error.value = null
  try {
    const ready = await props.checkout.reorder(props.order.request_id, [...selected.value], { replace: replace.value, signal: attempt.signal })
    if (!active || current !== generation) return
    if (ready) { close(); emit('ready') }
    else error.value = { message: 'Your selection changed while the quote was being prepared. Review it before trying again.' }
  } catch (problem) { if (active && current === generation && problem.code !== 'STALE_SCOPE') error.value = problem }
  finally { if (active && current === generation) busy.value = false }
}
onBeforeUnmount(() => { active = false; invalidate(); dialog.value?.close() })
</script>
<template>
  <button class="button secondary" :disabled="blocked || checkoutState.quoting" @click="open">Repeat selected products</button>
  <dialog ref="dialog" class="product-dialog reorder-dialog" aria-label="Repeat request products" @close="closed"><header><p class="eyebrow gold">{{ order.request_no }}</p><button class="icon-button" aria-label="Close repeat request" @click="close">×</button></header><form @submit.prevent="prepare"><div class="dialog-body"><h2>A fresh request.</h2><p class="small muted">Choose the products you need again. Current names, prices and availability will be checked. Previous charges and your PO reference will not carry over.</p><label v-for="line in order.items" :key="line.line_key" class="reorder-line"><input v-model="selected" type="checkbox" :value="line.line_key" :disabled="busy" :aria-label="`Repeat ${line.display_snapshot.model_name}, ${line.display_snapshot.color_name}`" /><div><OrderLine :line="line" /><p v-if="unavailable(line)" class="reorder-unavailable">No longer in your approved collection. Deselect to continue with other products.</p></div></label><label v-if="hasDraft" class="quote-confirmation"><input v-model="replace" type="checkbox" :disabled="busy" /><span>Replace my current selection ({{ checkoutState.lines.length }} products) with these products and the previous request’s delivery details.</span></label><div v-if="error" ref="errorSummary" class="alert error" role="alert" tabindex="-1"><p>{{ error.message }}</p><small v-if="error.traceId">Reference: {{ error.traceId }}</small></div></div><footer><button class="button secondary" type="button" @click="close">Keep browsing</button><button class="button primary" type="submit" :disabled="busy || blocked || !selected.length || (hasDraft && !replace)">{{ busy ? 'Preparing fresh quote…' : 'Review fresh quote' }}</button></footer></form></dialog>
</template>
