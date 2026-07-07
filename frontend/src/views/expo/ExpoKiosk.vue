<template>
  <div class="xk-root" @pointerdown="flow.touch()">
    <header class="xk-head">
      <div
        class="xk-brand"
        @pointerdown.stop="brandPressStart"
        @pointerup="brandPressEnd"
        @pointercancel="brandPressEnd"
      >莱 莎 · 健 康 假 发</div>
      <div class="xk-head-right">{{ stepLabel }}</div>
    </header>

    <main class="xk-stage">
      <AttractScreen v-if="flow.step.value === 'attract'" @start="flow.start($event)" />
      <RegisterScreen v-else-if="flow.step.value === 'register'" />
      <CaptureScreen v-else-if="flow.step.value === 'capture'" />
      <AnalyzingScreen v-else-if="flow.step.value === 'analyzing'" />
      <MatchingScreen v-else-if="flow.step.value === 'matching'" />
      <SceneScreen v-else-if="flow.step.value === 'scene'" />
      <ResultScreen v-else-if="flow.step.value === 'result'" />
      <SalesPanel v-else-if="flow.step.value === 'sales'" />
    </main>

    <div v-if="flow.errorText.value" class="xk-error">{{ flow.errorText.value }}</div>
  </div>
</template>

<script setup>
import { computed, provide } from 'vue'
import { useTryOnFlow } from './composables/useTryOnFlow'
import AttractScreen from './kiosk/AttractScreen.vue'
import RegisterScreen from './kiosk/RegisterScreen.vue'
import CaptureScreen from './kiosk/CaptureScreen.vue'
import AnalyzingScreen from './kiosk/AnalyzingScreen.vue'
import MatchingScreen from './kiosk/MatchingScreen.vue'
import SceneScreen from './kiosk/SceneScreen.vue'
import ResultScreen from './kiosk/ResultScreen.vue'
import SalesPanel from './kiosk/SalesPanel.vue'

const flow = useTryOnFlow()
provide('tryonFlow', flow)

const stepLabel = computed(() => ({
  attract: '', register: '快速登记', capture: '拍摄',
  analyzing: 'AI 面容气质解析', matching: '发型甄选',
  scene: '场景甄选',
  result: flow.mode.value === 'scene' ? '场景大片' : '试戴效果',
  sales: '销售模式',
}[flow.step.value] || ''))

// 长按品牌字 3 秒进入销售面板（有会话时才有意义）
let pressTimer = null
function brandPressStart() {
  if (!flow.sessionId.value || flow.step.value === 'sales') return
  pressTimer = setTimeout(() => flow.openSales(), 3000)
}
function brandPressEnd() {
  if (pressTimer) clearTimeout(pressTimer)
  pressTimer = null
}
</script>

<style>
/* kiosk 全局命名空间样式（非 scoped，供子屏共用；全部以 .xk- 前缀隔离） */
.xk-root {
  --xk-ink: #0c0a08;
  --xk-ink-2: #14110d;
  --xk-gold: #e8c479;
  --xk-gold-hi: #f7e3b0;
  --xk-gold-dim: #9a7d45;
  --xk-gold-line: rgba(232, 196, 121, 0.28);
  --xk-paper: #f3ead9;
  --xk-mut: #8d8371;

  position: fixed;
  inset: 0;
  display: flex;
  flex-direction: column;
  height: 100dvh;
  background:
    radial-gradient(70vw 40vh at 70% -10%, rgba(232, 196, 121, 0.08), transparent 60%),
    radial-gradient(50vw 30vh at 10% 110%, rgba(232, 196, 121, 0.05), transparent 60%),
    var(--xk-ink);
  color: var(--xk-paper);
  font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
  letter-spacing: 0.02em;
  overflow: hidden;
  user-select: none;
  -webkit-user-select: none;
}
.xk-head {
  flex: none;
  height: 52px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 22px;
  font-size: 12px;
  color: var(--xk-gold-dim);
  letter-spacing: 0.3em;
}
.xk-brand { cursor: default; }
.xk-stage { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.xk-error {
  position: absolute;
  left: 50%;
  bottom: 24px;
  transform: translateX(-50%);
  background: rgba(224, 144, 107, 0.15);
  border: 1px solid rgba(224, 144, 107, 0.5);
  color: #e0906b;
  font-size: 13px;
  padding: 10px 22px;
  border-radius: 24px;
  letter-spacing: 0.1em;
}

/* 共用元件 */
.xk-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 52px;
  padding: 0 44px;
  border: none;
  border-radius: 30px;
  font-size: 15px;
  letter-spacing: 0.28em;
  color: var(--xk-ink);
  background: linear-gradient(110deg, var(--xk-gold-dim), var(--xk-gold) 45%, var(--xk-gold-hi));
  box-shadow: 0 6px 26px rgba(232, 196, 121, 0.3);
  cursor: pointer;
}
.xk-btn:active { transform: scale(0.97); }
.xk-btn.ghost {
  background: transparent;
  color: var(--xk-gold);
  border: 1px solid var(--xk-gold-line);
  box-shadow: none;
}
.xk-title {
  font-family: 'Noto Serif SC', 'STSong', serif;
  font-size: 26px;
  font-weight: 600;
  text-align: center;
}
.xk-title em { font-style: italic; color: var(--xk-gold); }
.xk-sub {
  text-align: center;
  font-size: 12px;
  color: var(--xk-mut);
  letter-spacing: 0.2em;
  margin-top: 8px;
}
</style>
