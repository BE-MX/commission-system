<template>
  <Teleport to="body">
    <Transition name="modal-fade">
      <div v-if="visible" class="welcome-modal-overlay">
        <!-- 背景遮罩 -->
        <div class="welcome-modal-backdrop" @click="handleClose" />

        <!-- 弹框卡片 -->
        <Transition name="modal-card" appear>
          <div class="welcome-modal-card">
            <!-- 发光背景 -->
            <div class="welcome-modal-glow" />

            <!-- 顶部金色渐变线条 -->
            <div class="welcome-modal-topline" />

            <!-- 关闭按钮 -->
            <button class="welcome-modal-close" @click="handleClose">
              <el-icon><Close /></el-icon>
            </button>

            <!-- 粒子装饰 -->
            <div class="welcome-modal-particles">
              <span
                v-for="n in 6"
                :key="n"
                class="particle-dot"
                :style="particleStyle(n)"
              />
              <div class="particle-orb orb-right" />
              <div class="particle-orb orb-left" />
            </div>

            <!-- 内容区 -->
            <div class="welcome-modal-content">
              <!-- 头像 + 问候 -->
              <div class="welcome-avatar-section">
                <div class="welcome-avatar">
                  <img v-if="props.avatarUrl" :src="props.avatarUrl" alt="avatar" class="avatar-img" />
                  <span v-else>{{ userName[0] }}</span>
                  <div class="avatar-status" />
                </div>
                <div class="welcome-greeting">
                  <div class="greeting-main">
                    <el-icon class="greeting-icon"><component :is="greetingIcon" /></el-icon>
                    <span class="greeting-text">{{ greetingText }}，{{ userName }}</span>
                  </div>
                  <p class="greeting-sub">欢迎回到莱莎方舟综合管理平台</p>
                </div>
              </div>

              <!-- 日期徽章 -->
              <div class="welcome-date-badge">
                <el-icon class="date-icon"><Star /></el-icon>
                <span>{{ todayDate }}</span>
              </div>

              <!-- TIPS 卡片 -->
              <div class="welcome-tip-card">
                <div class="tip-header">
                  <div class="tip-icon-box">
                    <el-icon><ReadingLamp /></el-icon>
                  </div>
                  <span class="tip-label">每日 Tips</span>
                  <span class="tip-pulse" />
                </div>
                <div class="tip-body">
                  <div class="tip-icon-large">
                    <el-icon><Star /></el-icon>
                  </div>
                  <p class="tip-content">{{ dailyTip }}</p>
                </div>
              </div>

              <!-- 统计行 -->
              <div class="welcome-stats">
                <div
                  v-for="stat in stats"
                  :key="stat.label"
                  class="welcome-stat"
                >
                  <span class="stat-value" :style="{ color: stat.color }">{{ stat.value }}</span>
                  <span class="stat-label">{{ stat.label }}</span>
                </div>
              </div>

              <!-- 开始工作按钮 -->
              <button class="welcome-start-btn" @click="handleClose">
                开始工作
              </button>

              <!-- 今日不再显示 -->
              <label class="welcome-dont-show">
                <span
                  class="check-box"
                  :class="{ checked: dontShowAgain }"
                  @click.stop="dontShowAgain = !dontShowAgain"
                >
                  <el-icon v-if="dontShowAgain"><Check /></el-icon>
                </span>
                <span class="check-label">今日不再显示</span>
              </label>
            </div>
          </div>
        </Transition>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import {
  Close, Star, ReadingLamp, Sunny, Sunrise, Moon,
  PartlyCloudy, Check
} from '@element-plus/icons-vue'
import dailyTipsData from '@/assets/daily-tips.json'

const props = defineProps({
  userName: { type: String, default: '' },
  avatarUrl: { type: String, default: '' },
  pendingCount: { type: Number, default: 0 },
  shootCount: { type: Number, default: 0 },
})

const authStore = useAuthStore()
const visible = ref(false)
const dontShowAgain = ref(false)

// 时段问候
const greeting = computed(() => {
  const hour = new Date().getHours()
  if (hour < 6)  return { text: '深夜好', icon: Moon }
  if (hour < 9)  return { text: '早上好', icon: Sunrise }
  if (hour < 12) return { text: '上午好', icon: PartlyCloudy }
  if (hour < 14) return { text: '中午好', icon: Sunny }
  if (hour < 18) return { text: '下午好', icon: PartlyCloudy }
  if (hour < 21) return { text: '晚上好', icon: Moon }
  return { text: '夜深了', icon: Moon }
})

const greetingText = computed(() => greeting.value.text)
const greetingIcon = computed(() => greeting.value.icon)

// 今日日期
const todayDate = computed(() => {
  return new Date().toLocaleDateString('zh-CN', {
    year: 'numeric', month: 'long', day: 'numeric', weekday: 'long'
  })
})

// 每日 TIPS（从 1000 条中随机）
const dailyTip = computed(() => {
  if (!dailyTipsData || dailyTipsData.length === 0) return ''
  const idx = Math.floor(Math.random() * dailyTipsData.length)
  return dailyTipsData[idx]
})

// 统计行数据
const stats = computed(() => [
  { label: '待审批', value: String(props.pendingCount || 0), color: '#DC3545' },
  { label: '今日拍摄', value: String(props.shootCount || 0), color: '#2D9F6F' },
  { label: '待补充归属', value: String(props.pendingCount || 0), color: '#D4941C' },
])

// 粒子位置
function particleStyle(n) {
  return {
    left: `${15 + n * 14}%`,
    top: `${20 + (n % 3) * 25}%`,
    animationDelay: `${n * 0.3}s`,
    animationDuration: `${3 + n * 0.5}s`,
  }
}

// localStorage 键
const LS_KEY = 'leshine_welcome_last_shown'

function shouldShowToday() {
  const lastShown = localStorage.getItem(LS_KEY)
  const today = new Date().toDateString()
  return lastShown !== today
}

function markShownToday() {
  localStorage.setItem(LS_KEY, new Date().toDateString())
}

function handleClose() {
  if (dontShowAgain.value) {
    markShownToday()
  }
  visible.value = false
}

// 对外暴露的打开方法
function open() {
  if (shouldShowToday()) {
    visible.value = true
    markShownToday()
  }
}

// 自动显示（延迟 600ms）
onMounted(() => {
  if (shouldShowToday()) {
    setTimeout(() => {
      visible.value = true
      markShownToday()
    }, 600)
  }
})

defineExpose({ open })
</script>

<style scoped>
/* ===== 遮罩层 ===== */
.welcome-modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
}

.welcome-modal-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(10, 10, 15, 0.6);
  backdrop-filter: blur(12px);
}

/* ===== 弹框卡片 ===== */
.welcome-modal-card {
  position: relative;
  width: 100%;
  max-width: 420px;
  margin: 0 20px;
  border-radius: 20px;
  background: linear-gradient(180deg, #1a1a2e 0%, #14142b 100%);
  border: 1px solid rgba(255, 255, 255, 0.08);
  overflow: hidden;
  box-shadow: 0 25px 60px rgba(0, 0, 0, 0.5);
}

/* 发光背景 */
.welcome-modal-glow {
  position: absolute;
  inset: -1px;
  border-radius: 20px;
  background: linear-gradient(135deg, rgba(212, 175, 110, 0.25), rgba(0, 212, 255, 0.15), rgba(212, 175, 110, 0.25));
  filter: blur(16px);
  opacity: 0.5;
  z-index: 0;
}

/* 顶部金色线条 */
.welcome-modal-topline {
  position: relative;
  z-index: 2;
  height: 3px;
  background: linear-gradient(90deg, var(--color-gold), #00d4ff, var(--color-gold));
  background-size: 200% 100%;
  animation: topLineSlide 2s ease-out forwards, topLineShine 3s ease-in-out infinite 2s;
}

@keyframes topLineSlide {
  from { transform: scaleX(0); }
  to   { transform: scaleX(1); }
}

@keyframes topLineShine {
  0%, 100% { background-position: 0% 50%; }
  50%      { background-position: 100% 50%; }
}

/* 关闭按钮 */
.welcome-modal-close {
  position: absolute;
  top: 14px;
  right: 14px;
  z-index: 20;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.05);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: rgba(255, 255, 255, 0.4);
  transition: all 0.2s ease;
}
.welcome-modal-close:hover {
  color: #fff;
  background: rgba(255, 255, 255, 0.12);
  border-color: rgba(255, 255, 255, 0.2);
}

/* ===== 粒子装饰 ===== */
.welcome-modal-particles {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
  z-index: 1;
}

.particle-dot {
  position: absolute;
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: var(--color-gold);
  opacity: 0.3;
  animation: particleFloat 3s ease-in-out infinite;
}

@keyframes particleFloat {
  0%, 100% { transform: translateY(0) scale(1); opacity: 0.2; }
  50%      { transform: translateY(-12px) scale(1.4); opacity: 0.6; }
}

.particle-orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(40px);
  opacity: 0.15;
}
.orb-right {
  top: -20px;
  right: -20px;
  width: 120px;
  height: 120px;
  background: var(--color-gold);
}
.orb-left {
  bottom: -20px;
  left: -20px;
  width: 100px;
  height: 100px;
  background: #00d4ff;
}

/* ===== 内容区 ===== */
.welcome-modal-content {
  position: relative;
  z-index: 10;
  padding: 28px 24px 20px;
}

/* 头像 + 问候 */
.welcome-avatar-section {
  text-align: center;
  margin-bottom: 16px;
}

.welcome-avatar {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 64px;
  height: 64px;
  border-radius: 16px;
  background: linear-gradient(135deg, #d4af6e, #a08040);
  box-shadow: 0 4px 20px rgba(212, 175, 110, 0.3);
  margin-bottom: 12px;
  animation: avatarPop 0.6s cubic-bezier(0.34, 1.56, 0.64, 1) 0.2s both;
}
@keyframes avatarPop {
  from { transform: scale(0) rotate(-180deg); opacity: 0; }
  to   { transform: scale(1) rotate(0deg); opacity: 1; }
}

.welcome-avatar .avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.welcome-avatar span {
  font-size: 24px;
  font-weight: 700;
  color: #fff;
  font-family: var(--font-display);
}

.avatar-status {
  position: absolute;
  bottom: -3px;
  right: -3px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #16a34a;
  border: 3px solid #1a1a2e;
  animation: statusPop 0.3s ease 0.6s both;
}
@keyframes statusPop {
  from { transform: scale(0); }
  to   { transform: scale(1); }
}

.welcome-greeting {
  animation: fadeSlideUp 0.5s ease 0.3s both;
}

.greeting-main {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-bottom: 4px;
}

.greeting-icon {
  font-size: 18px;
  color: var(--color-gold);
}

.greeting-text {
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 700;
  color: #fff;
}

.greeting-sub {
  font-family: var(--font-body);
  font-size: 13px;
  color: rgba(255, 255, 255, 0.45);
  margin: 0;
}

/* 日期徽章 */
.welcome-date-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 0 auto 16px;
  padding: 5px 14px;
  border-radius: 100px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  animation: fadeSlideUp 0.5s ease 0.4s both;
}

.date-icon {
  font-size: 14px;
  color: var(--color-gold);
}

.welcome-date-badge span {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.55);
}

/* TIPS 卡片 */
.welcome-tip-card {
  padding: 14px 16px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  margin-bottom: 16px;
  animation: fadeSlideUp 0.5s ease 0.5s both;
}

.tip-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.tip-icon-box {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: rgba(245, 203, 92, 0.15);
  color: var(--color-gold);
  font-size: 14px;
}

.tip-label {
  font-family: var(--font-display);
  font-size: 11px;
  font-weight: 700;
  color: var(--color-gold);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.tip-pulse {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-gold);
  margin-left: auto;
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%      { opacity: 0.4; transform: scale(0.7); }
}

.tip-body {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.tip-icon-large {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: rgba(245, 203, 92, 0.1);
  color: var(--color-gold);
  font-size: 18px;
  flex-shrink: 0;
}

.tip-content {
  font-family: var(--font-body);
  font-size: 13px;
  color: rgba(255, 255, 255, 0.6);
  line-height: 1.6;
  margin: 0;
}

/* 统计行 */
.welcome-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-bottom: 16px;
  animation: fadeSlideUp 0.5s ease 0.6s both;
}

.welcome-stat {
  text-align: center;
  padding: 10px 0;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.stat-value {
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 700;
  line-height: 1;
}

.stat-label {
  display: block;
  font-size: 11px;
  color: rgba(255, 255, 255, 0.4);
  margin-top: 4px;
}

/* 开始工作按钮 */
.welcome-start-btn {
  width: 100%;
  height: 42px;
  border: none;
  border-radius: 12px;
  background: linear-gradient(135deg, #d4af6e, #c49b52);
  color: #fff;
  font-family: var(--font-display);
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s ease;
  animation: fadeSlideUp 0.5s ease 0.7s both;
}
.welcome-start-btn:hover {
  box-shadow: 0 4px 20px rgba(212, 175, 110, 0.3);
  transform: translateY(-1px);
}
.welcome-start-btn:active {
  transform: scale(0.98);
}

/* 今日不再显示 */
.welcome-dont-show {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: 12px;
  cursor: pointer;
  animation: fadeSlideUp 0.5s ease 0.8s both;
}

.check-box {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 4px;
  border: 1px solid rgba(255, 255, 255, 0.3);
  background: transparent;
  transition: all 0.2s ease;
  color: #0a0a0f;
  font-size: 12px;
}
.check-box.checked {
  background: var(--color-gold);
  border-color: var(--color-gold);
}

.check-label {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.4);
  transition: color 0.2s ease;
}
.welcome-dont-show:hover .check-label {
  color: rgba(255, 255, 255, 0.6);
}

/* ===== 通用动画 ===== */
@keyframes fadeSlideUp {
  from { opacity: 0; transform: translateY(20px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* ===== Transition 类 ===== */
.modal-fade-enter-active,
.modal-fade-leave-active {
  transition: opacity 0.3s ease;
}
.modal-fade-enter-from,
.modal-fade-leave-to {
  opacity: 0;
}

.modal-card-enter-active {
  transition: all 0.5s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.modal-card-leave-active {
  transition: all 0.3s ease;
}
.modal-card-enter-from {
  opacity: 0;
  transform: scale(0.85) translateY(40px);
}
.modal-card-leave-to {
  opacity: 0;
  transform: scale(0.9) translateY(20px);
}
</style>
