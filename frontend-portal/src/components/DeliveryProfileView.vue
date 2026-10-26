<script setup>
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { deliveryFields as fields, emptyDelivery } from '../state/delivery.mjs'
const props = defineProps({ api: { type: Object, required: true } })
const draft = reactive(emptyDelivery()), version = ref(null), busy = ref(false), loading = ref(true)
const error = ref(''), notice = ref(''), uncertain = ref(false)
const controller = new AbortController()
let disposed = false, sent = null
async function load() {
  loading.value = true; error.value = ''
  try {
    const data = await props.api.deliveryProfile(controller.signal)
    if (disposed) return
    version.value = data.row_version
    if (uncertain.value) {
      const matches = data.delivery && fields.every(([key]) => data.delivery[key] === sent[key])
      notice.value = matches ? 'Your delivery details are saved.' : 'Saved details differ. Review your entries before saving again.'
      uncertain.value = false; sent = null
    } else Object.assign(draft, emptyDelivery(), data.delivery || {})
  } catch (problem) { if (!disposed && problem.code !== 'STALE_SCOPE') error.value = problem.message }
  finally { if (!disposed) loading.value = false }
}
async function save() {
  if (busy.value || loading.value || uncertain.value || !version.value) return
  busy.value = true; error.value = ''; notice.value = ''
  sent = Object.fromEntries(fields.map(([key]) => [key, key === 'country_code' ? draft[key].trim().toUpperCase() : draft[key].trim()]))
  try {
    const data = await props.api.saveDeliveryProfile(version.value, sent)
    if (disposed) return
    version.value = data.row_version; Object.assign(draft, data.delivery)
    notice.value = 'Your delivery details are saved.'; sent = null
  } catch (problem) {
    if (disposed || problem.code === 'STALE_SCOPE') return
    error.value = problem.message
    if (problem.uncertain) uncertain.value = true
    else if (problem.code === 'VERSION_CONFLICT') version.value = null
  } finally { if (!disposed) busy.value = false }
}
onMounted(load)
onBeforeUnmount(() => { disposed = true; controller.abort(); sent = null; Object.assign(draft, emptyDelivery()) })
</script>

<template>
  <section class="collection-page delivery-profile-page">
    <header class="collection-heading"><div><p class="eyebrow gold">YOUR ACCOUNT</p><h1>Delivery details</h1><p class="muted">Save your contact and delivery address for future requests.</p></div></header>
    <p v-if="loading" role="status">Loading your delivery details…</p>
    <p v-if="error" class="alert error" role="alert">{{ error }}</p>
    <p v-if="notice" class="alert" role="status">{{ notice }}</p>
    <form class="checkout-card" @submit.prevent="save">
      <fieldset :disabled="loading || busy || uncertain || !version" class="delivery-profile-fields">
        <legend class="sr-only">Default delivery details</legend>
        <div class="delivery-grid"><label v-for="[key, label, autocomplete, max, required] in fields" :key="key">{{ label }}<input v-model="draft[key]" :name="key" :type="key === 'phone' ? 'tel' : 'text'" :autocomplete="autocomplete" :maxlength="max" :required="required" :minlength="key === 'phone' ? 3 : key === 'country_code' ? 2 : undefined" :pattern="key === 'country_code' ? '[A-Za-z]{2}' : undefined" /></label></div>
        <button class="button primary" type="submit">{{ busy ? 'Saving…' : 'Save delivery details' }}</button>
      </fieldset>
      <button v-if="uncertain || !version" type="button" class="button secondary" :disabled="loading || busy" @click="load">{{ uncertain ? 'Check saved details' : 'Reload saved details' }}</button>
    </form>
  </section>
</template>

<style scoped>
.delivery-profile-page { max-width: 880px; margin: 0 auto; }
.delivery-profile-fields { border: 0; margin: 0; padding: 0; min-width: 0; }
.delivery-profile-fields .button { margin-top: 24px; }
</style>
