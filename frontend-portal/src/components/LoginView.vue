<script setup>
import { nextTick, onBeforeUnmount, ref } from 'vue'
import BrandMark from './BrandMark.vue'
const props = defineProps({ api: { type: Object, required: true } })
const emit = defineEmits(['request-access'])
const email = ref(''), password = ref(''), busy = ref(false), error = ref(null), passwordInput = ref(null)
let active = true
onBeforeUnmount(() => { active = false; password.value = '' })
async function login() {
  if (busy.value) return
  busy.value = true; error.value = null
  try {
    await props.api.bootstrap()
    if (!active) return
    await props.api.login(email.value.trim(), password.value)
  } catch (problem) {
    if (active && problem.code !== 'STALE_SCOPE') error.value = problem
  } finally {
    password.value = ''
    if (active) {
      busy.value = false
      await nextTick()
      if (active && error.value) passwordInput.value?.focus()
    }
  }
}
</script>

<template>
  <main class="login-layout">
    <section class="brand-panel" aria-label="LeShine partner collection">
      <BrandMark />
      <div class="brand-story"><p class="eyebrow">THE PARTNER COLLECTION</p><h1>Good things<br />grow together.</h1><p>Your collection. Your shades.<br />A closer connection to LeShine.</p></div>
      <div class="brand-foot"><span>LESHINE / PARTNER ATELIER</span><span>01 — YOUR NEXT CHAPTER</span></div>
    </section>
    <section class="login-panel">
      <div class="login-form">
        <p class="eyebrow gold">WELCOME TO YOUR PRIVATE COLLECTION</p>
        <h2>A place for your<br />next possibility.</h2>
        <p class="muted">Sign in with the email and password provided by your LeShine representative.</p>
        <form @submit.prevent="login">
          <label for="email">Email address</label>
          <input id="email" v-model="email" type="email" autocomplete="username" inputmode="email" required maxlength="254" :disabled="busy" placeholder="you@yourcompany.com" />
          <label for="password">Password</label>
          <input id="password" ref="passwordInput" v-model="password" type="password" autocomplete="current-password" required minlength="8" maxlength="64" :disabled="busy" :aria-describedby="error ? 'login-error' : undefined" :aria-invalid="error?.code === 'AUTH_FAILED' ? 'true' : undefined" />
          <button class="button primary full" :disabled="busy">{{ busy ? 'Signing in…' : 'Sign in' }} <span aria-hidden="true">→</span></button>
        </form>
        <div v-if="error" id="login-error" class="alert error" role="alert"><p>{{ error.message }}</p><small v-if="error.traceId">Reference: {{ error.traceId }}</small></div>
        <div class="login-note"><span aria-hidden="true">◇</span><p>Access is managed by your LeShine representative.<br />Keep your password private.</p></div>
        <p class="access-help">Need access or a password reset? <button type="button" class="text-button" @click="emit('request-access')">Request customer portal access</button></p>
      </div>
      <footer class="login-footer"><span>PRIVATE PARTNER ACCESS</span><span>Powered by Ark</span></footer>
    </section>
  </main>
</template>
