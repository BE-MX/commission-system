<template>
  <div class="xk-root" @pointerdown="flow.touch()">
    <header class="xk-head">
      <div class="xk-head-side">
        <Transition name="xnav">
          <button v-if="showNav" class="xk-nav" :disabled="backDisabled" @click="flow.goBack()">‹ 上一步</button>
        </Transition>
        <div class="xk-brand" @click="brandClick">莱 莎 · 健 康 假 发</div>
      </div>
      <div class="xk-head-side">
        <span v-if="quota?.bound" class="xk-quota" :class="{ 'is-zero': quota.remaining === 0 }">
          剩余 {{ quota.remaining }} 张
        </span>
        <button
          v-if="flow.step.value === 'attract'"
          class="xk-nav"
          @click="requestLogout"
        >退出登录</button>
        <span class="xk-step">{{ stepLabel }}</span>
        <Transition name="xnav">
          <button v-if="showNav" class="xk-nav" @click="requestHome">⌂ 主页</button>
        </Transition>
      </div>
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

    <!-- 零额度阻断：遮住舞台区（顶栏导航保留，销售面板可查线索），
         服务端在 /generate 仍有硬阻断，这里只是现场体验层的提示 -->
    <Transition name="xnav">
      <div v-if="quotaBlocked" class="xk-quota-overlay">
        <div class="xk-quota-panel">
          <div class="xq-title">额度已用完</div>
          <div class="xq-sub">请联系门店管理员充值后再试</div>
        </div>
      </div>
    </Transition>

    <div v-if="flow.errorText.value" class="xk-error">{{ flow.errorText.value }}</div>

    <!-- 返回主页确认：拍照之后流程有实际代价（照片/分析/效果图），误触清场损失大 -->
    <Transition name="xconfirm">
      <div v-if="homeConfirm" class="xk-confirm" @click.self="homeConfirm = false">
        <div class="xk-confirm-panel">
          <div class="xc-title">返回主页将结束本次体验</div>
          <div class="xc-sub">当前客户的登记信息与效果图查看将被清空</div>
          <div class="xc-actions">
            <button class="xk-btn ghost" @click="homeConfirm = false">继续体验</button>
            <button class="xk-btn" @click="confirmHome">返回主页</button>
          </div>
        </div>
      </div>
    </Transition>

    <Transition name="xconfirm">
      <div v-if="logoutConfirm" class="xk-confirm" @click.self="cancelLogout">
        <div
          class="xk-confirm-panel"
          role="dialog"
          aria-modal="true"
          aria-labelledby="logout-confirm-title"
        >
          <div id="logout-confirm-title" class="xc-title">确认退出登录？</div>
          <div class="xc-sub">退出后需要重新输入展会设备账号才能继续使用</div>
          <div class="xc-actions">
            <button class="xk-btn ghost" :disabled="logoutPending" @click="cancelLogout">取消</button>
            <button class="xk-btn" :disabled="logoutPending" @click="confirmLogout">退出登录</button>
          </div>
        </div>
      </div>
    </Transition>

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
import { computed, onBeforeUnmount, onMounted, provide, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useTryOnFlow } from './composables/useTryOnFlow'
import { useStoreQuota } from './composables/useStoreQuota'
import AttractScreen from './kiosk/AttractScreen.vue'
import RegisterScreen from './kiosk/RegisterScreen.vue'
import CaptureScreen from './kiosk/CaptureScreen.vue'
import AnalyzingScreen from './kiosk/AnalyzingScreen.vue'
import MatchingScreen from './kiosk/MatchingScreen.vue'
import SceneScreen from './kiosk/SceneScreen.vue'
import ResultScreen from './kiosk/ResultScreen.vue'
import SalesPanel from './kiosk/SalesPanel.vue'

const flow = useTryOnFlow()
const authStore = useAuthStore()
provide('tryonFlow', flow)

// ── 门店额度（2026-08-06）──
// 30s 轮询 + 进入生成相关屏前刷新：现场对余额变动（充值/消耗）有实时感知诉求。
// 未绑定门店的老展会设备 quota.bound=false → 不显示、不阻断，行为与上线前一致。
const { quota, fetchQuota } = useStoreQuota({ kiosk: true, pollMs: 30000 })
// 销售面板是店员自查工具，零额度不遮——客户流程屏才需要阻断
const quotaBlocked = computed(() =>
  !!quota.value?.bound && quota.value.remaining === 0 && flow.step.value !== 'sales')

// ── 刘海屏安全区（2026-07-27）──
// APK 的 themes.xml 声明 windowLayoutInDisplayCutoutMode=shortEdges + 全屏沉浸，页面会被主动
// 画到刘海/状态栏底下。没有 viewport-fit=cover 时 WebView 不暴露 env(safe-area-inset-*)，
// 52px 高的顶栏正好整条落进系统手势区——「上一步 / 主页」看得见点不着（手机实测）。
// 只在本页改 meta、离开还原：全站其余页面（含 PC 与 /m/）的视口行为一个字不动。
let prevViewport = null
const viewportMeta = () => document.querySelector('meta[name="viewport"]')
onMounted(() => {
  const meta = viewportMeta()
  if (!meta || meta.content.includes('viewport-fit')) return
  prevViewport = meta.content
  meta.content = `${prevViewport}, viewport-fit=cover`
})
onBeforeUnmount(() => {
  const meta = viewportMeta()
  if (meta && prevViewport !== null) meta.content = prevViewport
})

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

// ── 全流程导航（2026-07-13）：attract 之外每屏都有「上一步 / 主页」 ──
const showNav = computed(() => flow.step.value !== 'attract')
// 生成中禁退：回甄选页选了款也按不了生成（generate 有忙态互斥），徒增困惑
const backDisabled = computed(() => flow.step.value === 'result' && flow.generating.value)

const homeConfirm = ref(false)
const logoutConfirm = ref(false)
const logoutPending = ref(false)
function requestHome() {
  if (!flow.sessionId.value) {
    flow.resetAll() // 未拍照建会话，流程无实际代价，直接回
    return
  }
  homeConfirm.value = true
  flow.touch()
}
function requestLogout() {
  logoutConfirm.value = true
  flow.touch()
}
function cancelLogout() {
  if (logoutPending.value) return
  logoutConfirm.value = false
}
function confirmHome() {
  homeConfirm.value = false
  flow.resetAll()
}
async function confirmLogout() {
  if (logoutPending.value) return
  logoutPending.value = true
  try {
    await authStore.logout({
      name: 'Login',
      query: { redirect: '/expo/kiosk' },
    })
  } finally {
    logoutPending.value = false
  }
}
// 60s 空闲自动清场等其他路径回到 attract 时，收掉残留的确认弹层；
// 进入生成相关屏（甄选/场景/结果）时刷新一次额度，生成扣减后余额即刻反映
watch(flow.step, s => {
  if (s === 'attract') homeConfirm.value = false
  if (['matching', 'scene', 'result'].includes(s)) fetchQuota()
})

// 点击品牌字进入销售面板（2026-07-13 亮哥指令：由长按 3 秒改为单击）。
// 面板已是线索列表，无会话也可进（销售随时查话术）；不做明显按钮、不给
// pointer 光标——入口对客户保持无痕，60s 空闲自动清场兜底共享屏隐私
function brandClick() {
  if (flow.step.value === 'sales') return
  flow.openSales()
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
  --xk-warn: #e0906b;

  position: fixed;
  inset: 0;
  display: flex;
  flex-direction: column;
  height: 100dvh;
  /* 安全区一次性收口：全局 box-sizing:border-box 让 padding 计进 100dvh，背景仍铺满刘海（不留白边），
     而 .xk-head/.xk-stage 以及 absolute inset:0 的装饰镜框、错误条都以 padding box 为准，自动避让 */
  padding:
    env(safe-area-inset-top) env(safe-area-inset-right)
    env(safe-area-inset-bottom) env(safe-area-inset-left);
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
.xk-brand { cursor: default; white-space: nowrap; }
.xk-head-side { display: flex; align-items: center; gap: 14px; min-width: 0; }
.xk-step { white-space: nowrap; }

/* 门店剩余额度：顶栏常驻；0 张变红（同 xk-error 的暖红） */
.xk-quota { white-space: nowrap; letter-spacing: 0.1em; color: var(--xk-gold); }
.xk-quota.is-zero { color: var(--xk-warn); }

/* 零额度遮罩：只盖舞台区（top 让开 52px 顶栏，主页/销售面板入口仍可用），
   z 72 压过镜框 60 与错误条 70，低于主页确认 75 与灯箱 80 */
.xk-quota-overlay {
  position: absolute;
  top: 52px; right: 0; bottom: 0; left: 0;
  z-index: 72;
  display: flex; align-items: center; justify-content: center;
  background: rgba(6, 5, 3, 0.82);
  -webkit-backdrop-filter: blur(6px); backdrop-filter: blur(6px);
}
.xk-quota-panel { text-align: center; padding: 30px 40px; }
.xq-title {
  font-family: 'Noto Serif SC', serif; font-size: 22px;
  letter-spacing: 0.14em; color: var(--xk-warn);
}
.xq-sub { margin-top: 12px; font-size: 13px; letter-spacing: 0.12em; color: var(--xk-mut); }

.xk-nav {
  flex: none; height: 34px; padding: 0 14px; border-radius: 18px; cursor: pointer;
  border: 1px solid var(--xk-gold-line); background: rgba(232, 196, 121, 0.04);
  color: var(--xk-gold-hi); font-size: 12px; letter-spacing: 0.14em;
  transition: transform 160ms cubic-bezier(0.23, 1, 0.32, 1), border-color 160ms ease, opacity 160ms ease;
}
.xk-nav:active { transform: scale(0.96); }
.xk-nav:disabled { opacity: 0.35; cursor: default; }
.xk-nav:disabled:active { transform: none; }
.xnav-enter-active, .xnav-leave-active { transition: opacity 200ms ease; }
.xnav-enter-from, .xnav-leave-to { opacity: 0; }

/* ── 返回主页确认弹层（z 75：压过镜框 60 与错误条 70，低于灯箱 80） ── */
.xk-confirm {
  /* fixed 相对视口，不吃 .xk-root 的安全区 padding，得自己收口 */
  position: fixed; inset: 0; z-index: 75;
  display: flex; align-items: center; justify-content: center;
  padding:
    calc(16px + env(safe-area-inset-top)) calc(16px + env(safe-area-inset-right))
    calc(16px + env(safe-area-inset-bottom)) calc(16px + env(safe-area-inset-left));
  background: rgba(6, 5, 3, 0.72);
  -webkit-backdrop-filter: blur(4px); backdrop-filter: blur(4px);
}
.xk-confirm-panel {
  display: flex; flex-direction: column; align-items: center;
  padding: 30px 34px 26px; border-radius: 20px;
  border: 1px solid var(--xk-gold-line);
  background: linear-gradient(160deg, var(--xk-ink-2), var(--xk-ink));
  box-shadow: 0 24px 70px rgba(0, 0, 0, 0.5), 0 0 40px rgba(232, 196, 121, 0.12);
}
.xc-title {
  font-family: 'Noto Serif SC', serif; font-size: 19px;
  letter-spacing: 0.1em; color: var(--xk-gold-hi);
}
.xc-sub { margin-top: 10px; font-size: 12px; letter-spacing: 0.12em; color: var(--xk-mut); }
.xc-actions { display: flex; gap: 14px; margin-top: 24px; }
.xc-actions .xk-btn { height: 46px; padding: 0 30px; font-size: 13px; }
/* 模态入场 240ms 强 ease-out，出场更快（非对称）；transform-origin 保持居中 */
.xconfirm-enter-active { transition: opacity 240ms cubic-bezier(0.23, 1, 0.32, 1); }
.xconfirm-enter-active .xk-confirm-panel { transition: transform 240ms cubic-bezier(0.23, 1, 0.32, 1); }
.xconfirm-leave-active { transition: opacity 160ms cubic-bezier(0.23, 1, 0.32, 1); }
.xconfirm-enter-from, .xconfirm-leave-to { opacity: 0; }
.xconfirm-enter-from .xk-confirm-panel { transform: scale(0.96); }
@media (prefers-reduced-motion: reduce) {
  .xconfirm-enter-from .xk-confirm-panel { transform: none; }
}
.xk-stage { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.xk-error {
  position: absolute;
  left: 50%;
  bottom: calc(24px + env(safe-area-inset-bottom)); /* 同上：绝对定位不吃父级安全区 padding */
  z-index: 70; /* 压在魔法镜框装饰层之上 */
  transform: translateX(-50%);
  background: rgba(224, 144, 107, 0.15);
  border: 1px solid rgba(224, 144, 107, 0.5);
  color: var(--xk-warn);
  font-size: 13px;
  padding: 10px 22px;
  border-radius: 24px;
  letter-spacing: 0.1em;
}

/* ── 魔法镜框（装饰层，z-index 60；xk-error 抬到 70 保证可读） ── */
/* 绝对定位以父级 padding box 的「边界」为基准，.xk-root 的安全区 padding 推不动它——
   四边得自己写 env()，否则金环顶部被刘海啃掉一段 */
.xk-mirror {
  position: absolute;
  top: env(safe-area-inset-top); right: env(safe-area-inset-right);
  bottom: env(safe-area-inset-bottom); left: env(safe-area-inset-left);
  pointer-events: none; z-index: 60; overflow: hidden;
}
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
.xk-btn:disabled { opacity: 0.45; cursor: default; }
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
/* ── 手机竖屏（≤560px）：顶栏保命断点 ──
   390px 屏上顶栏内容需 ~410px、可用仅 346px。两个 nowrap 文本被 flex 压缩后没有 overflow 收口，
   直接溢出各自盒子互相覆盖。取舍是砍掉步骤标签：每一屏都有大标题说明当前在哪一步，
   而导航按钮点不着是硬故障——装饰性信息给功能性按钮让路。*/
@media (max-width: 560px) {
  .xk-head { height: 46px; padding: 0 12px; }
  .xk-step { display: none; }
  .xk-quota { letter-spacing: 0.04em; }
  .xk-quota-overlay { top: 46px; }
  .xk-head-side { gap: 10px; }
  .xk-brand { min-width: 0; overflow: hidden; text-overflow: ellipsis; letter-spacing: 0.14em; }
  .xk-nav { height: 36px; padding: 0 12px; letter-spacing: 0.08em; }
}
</style>
