<template>
  <div class="xk-root" :data-step="flow.step.value" @pointerdown="flow.touch()">
    <header class="xk-head">
      <div class="xk-head-side">
        <Transition name="xnav">
          <button v-if="showNav" class="xk-nav" :disabled="backDisabled" @click="flow.goBack()">‹ 上一步</button>
        </Transition>
        <button class="xk-brand" aria-label="莱莎 · 进入销售模式" @click="brandClick"><span>LESHINE</span><small>莱莎 · 健康假发</small></button>
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

    <div v-if="flow.errorText.value" class="xk-error" role="alert">{{ flow.errorText.value }}</div>

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

    <AiIssueNotice />


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
import AiIssueNotice from './kiosk/AiIssueNotice.vue'

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

<style src="./kiosk/styles/atelier.css"></style>
