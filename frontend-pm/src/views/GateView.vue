<template>
  <div class="gate">
    <div class="gate-texture" aria-hidden="true"></div>

    <main class="gate-main">
      <div class="gate-seal rise">
        <img class="gate-seal-img" :src="sealUrl" width="120" height="120" alt="LeShine Hair" />
      </div>

      <p class="gate-eyebrow rise rise-1">LESHINE HAIR · PM HUB</p>
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
            placeholder="输入项目用户名（非姓名）"
            :disabled="busy"
            @input="errorShown = false"
          />
          <button class="gate-go" type="submit" :disabled="busy || !username" aria-label="进入">
            <span v-if="busy" class="spinner spinner-ink"></span>
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

// public 资产带构建 base 前缀，内网 /pm/ 入口下才不会落到主站根路径
const sealUrl = import.meta.env.BASE_URL + 'seal-logo.png'
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
    // HTTP 错误（401/429）统一防枚举提示；网络层错误（无 status）提示连接问题
    errorText.value = err?.status ? '无法验证，请联系亮哥' : '网络异常，请稍后再试'
    errorShown.value = true
    busy.value = false
    inputEl.value?.focus()
  }
}
</script>

<style scoped>
/* 门牌页 = 一张放大的 LeShine logo 金卡：金底 × 墨字，品牌第一眼 */
.gate {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
  padding: 40px 24px;
  background: var(--gold);
  color: var(--ink);
}

/* 金面肌理：极淡的墨点 + 中央提亮，近看有质感、远看是整块金 */
.gate-texture {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background-image: radial-gradient(rgba(28, 27, 25, 0.13) 1px, transparent 1px);
  background-size: 26px 26px;
  mask-image: radial-gradient(ellipse 62% 52% at 50% 46%, transparent 30%, black 78%);
  -webkit-mask-image: radial-gradient(ellipse 62% 52% at 50% 46%, transparent 30%, black 78%);
}
.gate-texture::after {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(ellipse 54% 42% at 50% 44%, rgba(255, 255, 255, 0.22), transparent 70%);
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

.gate-seal { margin-bottom: 30px; }
/* 圆形 logo 徽章入场：首访一次的仪式感（此后不再出现） */
.gate-seal-img {
  display: block;
  border-radius: 50%;
  animation: seal-in 700ms var(--ease-out) 120ms both;
}
@keyframes seal-in {
  from { opacity: 0; transform: scale(0.92); }
  to { opacity: 1; transform: scale(1); }
}

.gate-eyebrow {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.34em;
  color: rgba(28, 27, 25, 0.62);
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
  color: rgba(28, 27, 25, 0.68);
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
  border-top: 1px solid rgba(28, 27, 25, 0.4);
}
.gate-rule span {
  width: 5px;
  height: 5px;
  background: var(--ink);
  transform: rotate(45deg);
}

.gate-form { width: min(360px, 100%); }
.gate-field {
  display: flex;
  align-items: center;
  gap: 10px;
  border-bottom: 1.5px solid rgba(28, 27, 25, 0.45);
  padding-bottom: 10px;
  transition: border-color var(--dur-med) var(--ease-out);
}
.gate-field:focus-within { border-bottom-color: var(--ink); }
.gate-field.failed { border-bottom-color: var(--danger-on-gold); animation: shake 380ms var(--ease-out); }
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
.gate-input::placeholder { color: rgba(28, 27, 25, 0.42); }
.gate-go {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: var(--ink);
  color: var(--gold);
  transition: transform var(--dur-fast) var(--ease-out), opacity var(--dur-fast) var(--ease-out);
}
.gate-go:active { transform: scale(0.94); }
.gate-go:disabled { opacity: 0.35; cursor: not-allowed; }
@media (hover: hover) and (pointer: fine) {
  .gate-go:not(:disabled):hover { transform: scale(1.06); }
}
.spinner-ink {
  border-color: rgba(245, 199, 59, 0.35);
  border-top-color: var(--gold);
}
.gate-error {
  margin: 10px 0 0;
  font-size: 12.5px;
  color: var(--danger-on-gold);
  font-weight: 600;
  opacity: 0;
  transform: translateY(-3px);
  transition: opacity var(--dur-med) var(--ease-out), transform var(--dur-med) var(--ease-out);
  height: 1.4em;
}
.gate-error.shown { opacity: 1; transform: translateY(0); }

.gate-note {
  margin-top: 44px;
  font-size: 12px;
  color: rgba(28, 27, 25, 0.55);
  letter-spacing: 0.12em;
}
.gate-foot {
  position: absolute;
  bottom: 26px;
  font-size: 12px;
  color: rgba(28, 27, 25, 0.55);
  letter-spacing: 0.04em;
}
</style>
