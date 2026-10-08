<script setup>
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import BrandMark from './BrandMark.vue'

const props = defineProps({ api: { type: Object, required: true }, invitation: { type: String, default: '' } })
const email = ref(''), code = ref(''), challenge = ref(null), busy = ref(false), error = ref(null)
const now = ref(Date.now()), resendAt = ref(0), expiresAt = ref(0), codeInput = ref(null)
const countdown = computed(() => Math.max(0, Math.ceil((resendAt.value - now.value) / 1000)))
const expired = computed(() => challenge.value && now.value >= expiresAt.value)
const timer = setInterval(() => { now.value = Date.now() }, 1000)
let active = true
onBeforeUnmount(() => { active = false; clearInterval(timer); code.value = ''; challenge.value = null })

async function sendCode() {
  if (busy.value || countdown.value) return
  busy.value = true; error.value = null
  try {
    await props.api.bootstrap()
    const result = await props.api.challenge({ email: email.value.trim(), invitationToken: props.invitation || undefined })
    if (!active) return
    challenge.value = result.challenge_id
    code.value = ''
    now.value = Date.now()
    resendAt.value = now.value + result.resend_after * 1000
    expiresAt.value = now.value + result.expires_in * 1000
  } catch (problem) { if (active && problem.code !== 'STALE_SCOPE') error.value = problem }
  finally {
    if (active) {
      busy.value = false
      await nextTick()
      if (active && challenge.value) codeInput.value?.focus()
    }
  }
}

async function verify() {
  if (busy.value || expired.value) return
  busy.value = true; error.value = null
  try { await props.api.verify(challenge.value, code.value) }
  catch (problem) { if (active && problem.code !== 'STALE_SCOPE') { error.value = problem; code.value = '' } }
  finally {
    if (active) {
      busy.value = false
      await nextTick()
      if (active && challenge.value) codeInput.value?.focus()
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
        <p class="eyebrow gold">{{ invitation ? 'YOUR INVITATION' : 'WELCOME TO YOUR PRIVATE COLLECTION' }}</p>
        <h2>{{ challenge ? 'Check your inbox.' : 'A place for your\nnext possibility.' }}</h2>
        <p class="muted">{{ challenge ? 'If this email is eligible, a six-digit code is on its way. Enter it below to continue.' : 'Sign in with the email invited by your LeShine representative.' }}</p>
        <form v-if="!challenge" @submit.prevent="sendCode">
          <label for="email">Email address</label>
          <input id="email" v-model="email" type="email" autocomplete="email" inputmode="email" required maxlength="254" :disabled="busy" :aria-describedby="error ? 'login-error' : undefined" placeholder="you@yourcompany.com" />
          <button class="button primary full" :disabled="busy">{{ busy ? 'Sending your code…' : 'Continue with email' }} <span aria-hidden="true">→</span></button>
        </form>
        <form v-else @submit.prevent="verify">
          <div class="email-review"><span>{{ email }}</span><button class="text-button" type="button" :disabled="busy" @click="challenge = null; code = ''; error = null">Change</button></div>
          <label for="code">Verification code</label>
          <input id="code" ref="codeInput" v-model="code" class="code-input" type="text" autocomplete="one-time-code" inputmode="numeric" pattern="[0-9]{6}" minlength="6" maxlength="6" required :disabled="busy" :aria-describedby="error ? 'code-help login-error' : 'code-help'" :aria-invalid="error?.code === 'AUTH_FAILED' ? 'true' : undefined" />
          <p id="code-help" class="small muted">{{ expired ? 'This code has expired. Request a new code below.' : 'Use the latest code sent to your inbox.' }}</p>
          <button class="button primary full" :disabled="busy || expired">{{ busy ? 'Verifying…' : (invitation ? 'Activate your access' : 'Enter your collection') }} <span aria-hidden="true">→</span></button>
          <button class="text-button resend" type="button" :disabled="busy || countdown > 0" @click="sendCode">{{ countdown ? `Resend available in ${countdown}s` : 'Send a new code' }}</button>
        </form>
        <div v-if="error" id="login-error" class="alert error" role="alert"><p>{{ error.message }}</p><small v-if="error.traceId">Reference: {{ error.traceId }}</small></div>
        <div class="login-note"><span aria-hidden="true">◇</span><p>Access is managed by your LeShine representative.<br />No password to remember.</p></div>
        <p class="access-help">Need access? Contact your LeShine representative.</p>
      </div>
      <footer class="login-footer"><span>PRIVATE PARTNER ACCESS</span><span>Powered by Ark</span></footer>
    </section>
  </main>
</template>
