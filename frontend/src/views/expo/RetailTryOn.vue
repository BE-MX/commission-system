<template>
  <div class="xk-root retail-tryon" :data-step="flow.step.value" @pointerdown="flow.touch()">
    <header class="xk-head">
      <div class="xk-head-side">
        <button class="xk-nav retail-exit" @click="returnToMall">‹ 返回商城</button>
        <span class="xk-brand retail-brand"><span>LESHINE</span><small>莱莎 · AI 智能试戴</small></span>
      </div>
      <div class="xk-head-side">
        <span class="retail-free">零售客户专享 · 一次免费体验</span>
        <Transition name="xnav"><button v-if="showNav" class="xk-nav" :disabled="backDisabled" @click="flow.goBack()">‹ 上一步</button></Transition>
        <Transition name="xnav"><button v-if="showNav" class="xk-nav" @click="requestHome">⌂ 主页</button></Transition>
      </div>
    </header>

    <nav v-if="journeyVisible" class="xk-journey" aria-label="试戴进度">
      <ol><li v-for="(item, index) in journeySteps" :key="item.key" :class="{ on:index===journeyIndex, done:index<journeyIndex }"><i>{{ index < journeyIndex ? '✓' : index + 1 }}</i><span>{{ item.label }}</span></li></ol>
      <span class="xk-mode-chip" :class="{ beauty: flow.photoProcessingMode.value === 'beauty' }">{{ flow.photoProcessingMode.value === 'beauty' ? '焕颜精修' : '原照保真' }}</span>
    </nav>

    <div v-if="flow.errorText.value" class="xk-error" role="alert">{{ flow.errorText.value }}</div>
    <main v-if="restoring" class="xk-stage retail-restoring"><p>正在恢复您的试戴记录…</p></main>
    <main v-else class="xk-stage">
      <RetailAttractScreen v-if="flow.step.value === 'attract'" @start="flow.start('tryon')" />
      <RegisterScreen v-else-if="flow.step.value === 'register'" />
      <CaptureScreen v-else-if="flow.step.value === 'capture'" />
      <AnalyzingScreen v-else-if="flow.step.value === 'analyzing'" />
      <MatchingScreen v-else-if="flow.step.value === 'matching'" />
      <ResultScreen v-else-if="flow.step.value === 'result'" />
    </main>
    <AiIssueNotice />

    <Transition name="xconfirm"><div v-if="homeConfirm" class="xk-confirm" @click.self="homeConfirm=false"><div class="xk-confirm-panel"><div class="xc-title">返回主页将结束当前步骤</div><div class="xc-sub">已使用的免费资格不会恢复，生成完成前请尽量不要退出。</div><div class="xc-actions"><button class="xk-btn ghost" @click="homeConfirm=false">继续体验</button><button class="xk-btn" @click="confirmHome">返回主页</button></div></div></div></Transition>
  </div>
</template>

<script setup>
import { computed, onMounted, provide, ref } from 'vue'
import { useTryOnFlow } from './composables/useTryOnFlow'
import { getRetailTryOnReturnUrl } from './retailTryOnSession'
import RetailAttractScreen from './kiosk/RetailAttractScreen.vue'
import RegisterScreen from './kiosk/RegisterScreen.vue'
import CaptureScreen from './kiosk/CaptureScreen.vue'
import AnalyzingScreen from './kiosk/AnalyzingScreen.vue'
import MatchingScreen from './kiosk/MatchingScreen.vue'
import ResultScreen from './kiosk/ResultScreen.vue'
import AiIssueNotice from './kiosk/AiIssueNotice.vue'

const flow = useTryOnFlow({ retail: true })
provide('tryonFlow', flow)
const restoring = ref(true)
onMounted(async () => {
  await flow.resumeRetailSession()
  restoring.value = false
})
const showNav = computed(() => flow.step.value !== 'attract' && !flow.sessionId.value)
const backDisabled = computed(() => flow.step.value === 'result' && flow.generating.value)
const journeyVisible = computed(() => ['capture','analyzing','matching','result'].includes(flow.step.value))
const journeySteps = [{ key:'capture',label:'照片' },{ key:'matching',label:'选发型' },{ key:'generate',label:'生成' },{ key:'result',label:'对比' }]
const journeyIndex = computed(() => {
  if (['capture','analyzing'].includes(flow.step.value)) return 0
  if (flow.step.value === 'matching') return 1
  if (flow.step.value === 'result' && flow.generating.value && !flow.doneResults.value.length) return 2
  return flow.step.value === 'result' ? 3 : 0
})
const homeConfirm = ref(false)
function requestHome() { if (!flow.sessionId.value) flow.resetAll(); else returnToMall() }
function confirmHome() { homeConfirm.value = false; flow.resetAll() }
function returnToMall() {
  const url = getRetailTryOnReturnUrl()
  try { window.top.location.href = url } catch { window.location.href = url }
}
</script>

<style src="./kiosk/styles/atelier.css"></style>
<style scoped>
.retail-brand { cursor:default; }.retail-exit { color:var(--xk-gold-hi); border-color:var(--xk-gold-line); }.retail-free { color:var(--xk-gold); font-size:12px; letter-spacing:.08em; }
.retail-restoring{display:grid;place-items:center;color:var(--xk-gold);font-size:18px}
.retail-tryon :deep(.side-stack > button:last-child),.retail-tryon :deep(.fallback > button){display:none}.retail-tryon :deep(.side-stack){justify-content:center}
@media(max-width:600px){.retail-free{display:none}.retail-brand small{display:none}.retail-exit{padding:0 10px}}
</style>
