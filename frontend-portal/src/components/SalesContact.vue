<script setup>
import { nextTick, onBeforeUnmount, ref } from 'vue'
const props = defineProps({ api: { type: Object, required: true } })
const dialog = ref(null), contact = ref(null), busy = ref(false), error = ref('')
let controller, sequence = 0, opener
async function load() {
  const current = ++sequence
  controller?.abort(); controller = new AbortController()
  contact.value = null; error.value = ''; busy.value = true
  try {
    const result = await props.api.salesContact(controller.signal)
    if (current === sequence) contact.value = result.contact
  } catch (problem) {
    if (current === sequence && !['STALE_SCOPE', 'REQUEST_ABORTED'].includes(problem.code)) error.value = problem.message
  } finally { if (current === sequence) busy.value = false }
}
async function open(event) { opener = event.currentTarget; await nextTick(); dialog.value.showModal(); load() }
function clear() { sequence++; controller?.abort(); contact.value = null; busy.value = false; error.value = '' }
function close() { clear(); dialog.value?.close(); opener?.focus() }
function focus() { if (dialog.value?.open) load() }
const unsubscribe = props.api.subscribe(() => close())
window.addEventListener('focus', focus)
onBeforeUnmount(() => { clear(); unsubscribe(); window.removeEventListener('focus', focus); dialog.value?.close() })
</script>

<template>
  <button class="text-button" @click="open">Contact your representative</button>
  <dialog ref="dialog" class="contact-dialog" aria-labelledby="contact-title" @cancel.prevent="close" @close="clear" @click="event => { if (event.target === dialog) close() }">
    <header><p class="eyebrow gold">PERSONAL SUPPORT</p><button class="icon-button" aria-label="Close contact" @click="close">×</button></header>
    <h2 id="contact-title">Your LeShine representative</h2>
    <p v-if="busy" role="status">Finding your current contact…</p>
    <p v-else-if="error" role="alert">{{ error }}</p>
    <template v-else-if="contact"><h3>{{ contact.display_name }}</h3><p class="muted">Here to help with your collection and order requests.</p><div class="contact-links"><a v-if="contact.email" class="button secondary" :href="'mailto:' + encodeURIComponent(contact.email)">Email {{ contact.display_name }}</a><a v-if="contact.whatsapp" class="button primary" :href="'https://wa.me/' + contact.whatsapp.slice(1)" target="_blank" rel="noopener noreferrer">Chat on WhatsApp</a></div><p class="small muted">{{ contact.email }}<span v-if="contact.email && contact.whatsapp"> · </span>{{ contact.whatsapp }}</p></template>
    <p v-else>Your representative’s contact details are not available here yet. Please use your existing LeShine contact channel.</p>
    <footer><button class="text-button" :disabled="busy" @click="load">Refresh contact</button><button class="button secondary" @click="close">Close</button></footer>
  </dialog>
</template>

<style scoped>
.contact-dialog { width: min(520px, calc(100vw - 32px)); box-sizing: border-box; max-height: calc(100dvh - 32px); overflow: auto; padding: 28px; border: 1px solid var(--portal-border); border-radius: 18px; background: var(--portal-white); color: var(--portal-ink); box-shadow: var(--portal-shadow); }
.contact-dialog::backdrop { background: var(--portal-backdrop); }
header, footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
h2 { font-size: 26px; line-height: 1.2; } h3 { font-size: 20px; }
p, h3 { overflow-wrap: anywhere; }
.contact-links { display: flex; flex-wrap: wrap; gap: 12px; margin: 24px 0; }
.contact-links a { white-space: normal; overflow-wrap: anywhere; text-decoration: none; }
footer { margin-top: 28px; }
@media (max-width: 400px) { .contact-dialog { padding: 20px; } .contact-links { flex-direction: column; } }
</style>
