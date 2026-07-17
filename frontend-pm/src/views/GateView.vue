<template>
  <div class="gate">
    <div class="gate-texture" aria-hidden="true"></div>

    <main class="gate-main">
      <div class="gate-seal rise">
        <svg width="92" height="92" viewBox="0 0 92 92" role="img" aria-label="莱莎项目站印鉴">
          <circle class="seal-ring seal-ring-outer" cx="46" cy="46" r="41" fill="none" stroke="currentColor" stroke-width="2.2"/>
          <circle class="seal-ring seal-ring-inner" cx="46" cy="46" r="32" fill="none" stroke="currentColor" stroke-width="0.9"/>
          <text x="46" y="56" text-anchor="middle" font-size="33" fill="currentColor" style="font-family: var(--font-serif)">莱</text>
        </svg>
      </div>

      <p class="gate-eyebrow rise rise-1">LESHINE ARK · PM HUB</p>
      <h1 class="gate-title rise rise-2">莱莎 AI 陪跑项目站</h1>
      <p class="gate-sub rise rise-3">阿里国际站智能体搭建 · 资料与任务协作</p>

      <div class="gate-rule rise rise-3" aria-hidden="true"><span></span></div>

      <form class="gate-form rise rise-4" @submit.prevent="submit">
        <div class="gate-field" :class="{ busy, failed: errorShown }">
          <input
            ref="inputEl"
            v-model.trim="username"
            class="gate-input"
            type="text"
            autocomplete="off"
            autocapitalize="off"
            spellcheck="false"
            placeholder="输入你的项目用户名"
            :disabled="busy"
            @input="errorShown = false"
          />
          <button class="gate-go" type="submit" :disabled="busy || !username" aria-label="进入">
            <span v-if="busy" class="spinner"></span>
            <svg v-else viewBox="0 0 20 20" width="18" height="18">
              <path d="M3 10h12M11 5.5 15.5 10 11 14.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </button>
        </div>
        <p class="gate-error" :class="{ shown: errorShown }" role="alert">{{ errorText }}</p>
      </form>

      <p class="gate-note rise rise-5">仅限项目成员 · 无密码进入 · 全部操作留痕</p>
    </main>

    <footer class="gate-foot rise rise-5">
      <span>进不去？找亮哥要用户名</span>
    </footer>
  </div>
</template>

<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { entry } from '../api/index.js'
import { identity } from '../stores/identity.js'

const router = useRouter()
const username = ref('')
const busy = ref(false)
const errorShown = ref(false)
const errorText = ref('无法验证，请联系亮哥')
const inputEl = ref(null)

onMounted(async () => {
  if (identity.token) {
    router.replace({ name: 'dashboard' })
    return
  }
  await nextTick()
  inputEl.value?.focus()
})

async function submit() {
  if (busy.value || !username.value) return
  busy.value = true
  errorShown.value = false
  try {
    const data = await entry(username.value)
    identity.signIn(data)
    router.replace({ name: 'dashboard' })
  } catch (err) {
    errorText.value = err?.status === 0 ? '网络异常，请稍后再试' : '无法验证，请联系亮哥'
    errorShown.value = true
    busy.value = false
    inputEl.value?.focus()
  }
}
</script>

<style scoped>
.gate {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
  padding: 40px 24px;
}

/* 纸面肌理：极淡的网点 + 中央暖晕，近看有质感、远看是留白 */
.gate-texture {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background-image: radial-gradient(rgba(28, 27, 25, 0.055) 1px, transparent 1px);
  background-size: 26px 26px;
  mask-image: radial-gradient(ellipse 62% 52% at 50% 46%, transparent 30%, black 78%);
  -webkit-mask-image: radial-gradient(ellipse 62% 52% at 50% 46%, transparent 30%, black 78%);
}
.gate-texture::after {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(ellipse 54% 42% at 50% 44%, rgba(178, 58, 38, 0.045), transparent 70%);
}

.gate-main {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  max-width: 560px;
  width: 100%;
}

.gate-seal { color: var(--cinnabar); margin-bottom: 30px; }
/* 印鉴画圆：首访一次的仪式感（此后不再出现，不做循环动画） */
.seal-ring {
  stroke-dasharray: 300;
  stroke-dashoffset: 300;
  transform-origin: center;
  transform: rotate(-90deg);
  animation: seal-draw 900ms var(--ease-in-out) 120ms forwards;
}
.seal-ring-inner { animation-delay: 420ms; animation-duration: 700ms; }
@keyframes seal-draw { to { stroke-dashoffset: 0; } }

.gate-eyebrow {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.34em;
  color: var(--ink-3);
  margin: 0 0 18px;
}
.gate-title {
  font-family: var(--font-serif);
  font-size: clamp(34px, 6vw, 46px);
  font-weight: 600;
  letter-spacing: 0.06em;
  margin: 0;
}
.gate-sub {
  margin: 14px 0 0;
  color: var(--ink-3);
  font-size: 14px;
  letter-spacing: 0.08em;
}

.gate-rule {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 34px 0 30px;
  width: 220px;
}
.gate-rule::before,
.gate-rule::after {
  content: '';
  flex: 1;
  border-top: 1px solid var(--hairline-strong);
}
.gate-rule span {
  width: 5px;
  height: 5px;
  background: var(--cinnabar);
  transform: rotate(45deg);
}

.gate-form { width: min(360px, 100%); }
.gate-field {
  display: flex;
  align-items: center;
  gap: 10px;
  border-bottom: 1px solid var(--hairline-strong);
  padding-bottom: 10px;
  transition: border-color var(--dur-med) var(--ease-out);
}
.gate-field:focus-within { border-bottom-color: var(--ink); }
.gate-field.failed { border-bottom-color: var(--cinnabar); animation: shake 380ms var(--ease-out); }
@keyframes shake {
  20% { transform: translateX(-5px); }
  45% { transform: translateX(4px); }
  70% { transform: translateX(-2px); }
  100% { transform: translateX(0); }
}
.gate-input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: 16.5px;
  padding: 6px 2px;
  color: var(--ink);
  letter-spacing: 0.02em;
}
.gate-input::placeholder { color: var(--ink-4); }
.gate-go {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  color: var(--ink-3);
  transition: color var(--dur-fast) var(--ease-out),
              background var(--dur-fast) var(--ease-out),
              transform var(--dur-fast) var(--ease-out);
}
.gate-go:active { transform: scale(0.94); }
.gate-go:disabled { opacity: 0.4; cursor: not-allowed; }
@media (hover: hover) and (pointer: fine) {
  .gate-go:not(:disabled):hover { color: #fff; background: var(--cinnabar); }
}
.gate-error {
  margin: 10px 0 0;
  font-size: 12.5px;
  color: var(--cinnabar);
  opacity: 0;
  transform: translateY(-3px);
  transition: opacity var(--dur-med) var(--ease-out), transform var(--dur-med) var(--ease-out);
  height: 1.4em;
}
.gate-error.shown { opacity: 1; transform: translateY(0); }

.gate-note {
  margin-top: 44px;
  font-size: 12px;
  color: var(--ink-4);
  letter-spacing: 0.12em;
}
.gate-foot {
  position: absolute;
  bottom: 26px;
  font-size: 12px;
  color: var(--ink-4);
  letter-spacing: 0.04em;
}
</style>
