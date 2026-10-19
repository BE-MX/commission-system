<script setup>
import { ref } from 'vue'
import BrandMark from './BrandMark.vue'
const props = defineProps({ api: { type: Object, required: true } })
const fullName = ref(''), phone = ref(''), email = ref(''), busy = ref(false), done = ref(false), error = ref(null)
async function submit() {
  if (busy.value) return
  busy.value = true; error.value = null
  try { await props.api.bootstrap(); await props.api.accessRequest({ full_name: fullName.value.trim(), phone: phone.value.trim(), email: email.value.trim() }); done.value = true }
  catch (problem) { error.value = problem }
  finally { busy.value = false }
}
</script>

<template>
  <main class="access-request-layout">
    <section class="access-request-panel" aria-labelledby="access-request-title">
      <BrandMark />
      <p class="eyebrow gold">PRIVATE PARTNER ACCESS</p>
      <h1 id="access-request-title">Request your<br />customer portal access.</h1>
      <p class="muted">Tell us who you are. Your LeShine representative will review the request and email you a secure password setup link after approval.</p>
      <div v-if="done" class="alert success" role="status"><h2>Request received.</h2><p>We will review your details and contact you at the email address provided. Do not submit another request while it is under review.</p></div>
      <form v-else @submit.prevent="submit">
        <label for="request-name">Full name</label><input id="request-name" v-model="fullName" required maxlength="100" autocomplete="name" :disabled="busy" />
        <label for="request-phone">Phone number</label><input id="request-phone" v-model="phone" required maxlength="40" autocomplete="tel" :disabled="busy" />
        <label for="request-email">Email address</label><input id="request-email" v-model="email" required maxlength="254" type="email" autocomplete="email" :disabled="busy" />
        <button class="button primary full" :disabled="busy">{{ busy ? 'Sending request…' : 'Request access' }} <span aria-hidden="true">→</span></button>
      </form>
      <div v-if="error" class="alert error" role="alert"><p>{{ error.message }}</p></div>
      <a v-if="done" class="button secondary full" href="/login">Return to sign in</a>
      <a v-else class="text-button access-back" href="/login">Already have access? Sign in</a>
    </section>
  </main>
</template>
