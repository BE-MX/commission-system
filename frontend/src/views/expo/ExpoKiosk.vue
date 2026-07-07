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

    <!-- 魔法镜框：流光金环 + 四角饰件 + 金尘粒子（纯装饰层，pointer-events 穿透） -->
    <div class="xk-mirror" aria-hidden="true">
      <div class="xk-mirror-glow" />
      <div class="xk-mirror-ring" />
      <div class="xk-mirror-line" />
      <i v-for="c in ['tl', 'tr', 'bl', 'br']" :key="c" :class="['xk-mirror-corner', c]" />
      <span
        v-for="(p, i) in dust" :key="'d' + i" class="xk-dust"
        :style="{ left: p.left, width: p.size, height: p.size,
                  animationDuration: p.dur, animationDelay: p.delay, '--drift': p.drift }"
      />
    </div>
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

// 金尘粒子：挂载时一次性生成随机轨迹；负延迟让首屏就有粒子在途，不用等一个周期
const dust = Array.from({ length: 18 }, () => ({
  left: `${(Math.random() * 100).toFixed(1)}%`,
  size: `${(2 + Math.random() * 3).toFixed(1)}px`,
  dur: `${(7 + Math.random() * 8).toFixed(1)}s`,
  delay: `${(-Math.random() * 12).toFixed(1)}s`,
  drift: `${((Math.random() - 0.5) * 90).toFixed(0)}px`,
}))

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
  z-index: 70; /* 压在魔法镜框装饰层之上 */
  transform: translateX(-50%);
  background: rgba(224, 144, 107, 0.15);
  border: 1px solid rgba(224, 144, 107, 0.5);
  color: #e0906b;
  font-size: 13px;
  padding: 10px 22px;
  border-radius: 24px;
  letter-spacing: 0.1em;
}

/* ── 魔法镜框（装饰层，z-index 60；xk-error 抬到 70 保证可读） ── */
.xk-mirror { position: absolute; inset: 0; pointer-events: none; z-index: 60; overflow: hidden; }
/* 流光金环：conic 高光沿边框匀速巡游（constant motion 用 linear）；
   @property 不支持的旧内核不插值 → 退化为静态金环，不报错 */
@property --xk-sweep {
  syntax: '<angle>';
  initial-value: 0deg;
  inherits: false;
}
.xk-mirror-ring {
  position: absolute; inset: 8px; border-radius: 22px; padding: 1.6px;
  background: conic-gradient(from var(--xk-sweep, 0deg),
    rgba(232, 196, 121, 0.07), rgba(232, 196, 121, 0.5) 12%,
    rgba(247, 227, 176, 0.95) 18%, rgba(232, 196, 121, 0.4) 26%,
    rgba(232, 196, 121, 0.07) 42%, rgba(232, 196, 121, 0.3) 66%,
    rgba(232, 196, 121, 0.07) 84%, rgba(232, 196, 121, 0.07));
  -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  -webkit-mask-composite: xor;
  mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  mask-composite: exclude;
  animation: xk-sweep 9s linear infinite;
}
@keyframes xk-sweep { to { --xk-sweep: 360deg; } }
.xk-mirror-line { position: absolute; inset: 14px; border: 1px solid rgba(232, 196, 121, 0.14); border-radius: 18px; }
.xk-mirror-glow {
  position: absolute; inset: 8px; border-radius: 22px;
  box-shadow: inset 0 0 64px rgba(232, 196, 121, 0.07), inset 0 0 14px rgba(232, 196, 121, 0.1);
  animation: xk-breathe 5.5s ease-in-out infinite;
}
@keyframes xk-breathe { 0%, 100% { opacity: 0.55; } 50% { opacity: 1; } }
/* 四角饰件：双线包角 + 发光菱钻 */
.xk-mirror-corner { position: absolute; width: 34px; height: 34px; }
.xk-mirror-corner::before { content: ''; position: absolute; inset: 0; border: 2px solid var(--xk-gold); opacity: 0.85; }
.xk-mirror-corner::after {
  content: ''; position: absolute; width: 6px; height: 6px;
  background: var(--xk-gold-hi); transform: rotate(45deg);
  box-shadow: 0 0 8px var(--xk-gold);
}
.xk-mirror-corner.tl { top: 8px; left: 8px; }
.xk-mirror-corner.tl::before { border-right: 0; border-bottom: 0; border-radius: 22px 0 0 0; }
.xk-mirror-corner.tl::after { top: -2px; left: -2px; }
.xk-mirror-corner.tr { top: 8px; right: 8px; }
.xk-mirror-corner.tr::before { border-left: 0; border-bottom: 0; border-radius: 0 22px 0 0; }
.xk-mirror-corner.tr::after { top: -2px; right: -2px; }
.xk-mirror-corner.bl { bottom: 8px; left: 8px; }
.xk-mirror-corner.bl::before { border-right: 0; border-top: 0; border-radius: 0 0 0 22px; }
.xk-mirror-corner.bl::after { bottom: -2px; left: -2px; }
.xk-mirror-corner.br { bottom: 8px; right: 8px; }
.xk-mirror-corner.br::before { border-left: 0; border-top: 0; border-radius: 0 0 22px 0; }
.xk-mirror-corner.br::after { bottom: -2px; right: -2px; }
/* 金尘粒子：底部升起 + 横向漂移，只动 transform/opacity */
.xk-dust {
  position: absolute; bottom: -6px; border-radius: 50%;
  background: radial-gradient(circle at 35% 30%, var(--xk-gold-hi), var(--xk-gold) 70%);
  box-shadow: 0 0 6px rgba(232, 196, 121, 0.8);
  opacity: 0;
  animation-name: xk-dust-rise;
  animation-timing-function: linear;
  animation-iteration-count: infinite;
}
@keyframes xk-dust-rise {
  0% { transform: translate3d(0, 0, 0) scale(0.6); opacity: 0; }
  8% { opacity: 0.85; }
  60% { opacity: 0.45; }
  100% { transform: translate3d(var(--drift), -104vh, 0) scale(1); opacity: 0; }
}
@media (prefers-reduced-motion: reduce) {
  .xk-mirror-ring, .xk-mirror-glow { animation: none; }
  .xk-dust { display: none; }
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
