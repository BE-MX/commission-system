<template>
  <div class="dashboard-hero">
    <div class="hero-content">
      <div class="hero-tag">ARK PLATFORM</div>
      <div class="hero-user-row">
        <div class="hero-avatar" v-if="authStore.user?.avatar_url">
          <img :src="authStore.user.avatar_url" alt="avatar" />
        </div>
        <div class="hero-avatar avatar-fallback" v-else>
          {{ (authStore.user?.real_name || '用户')[0] }}
        </div>
        <h1 class="hero-greeting">
          {{ authStore.user?.real_name || '用户' }}，{{ data.greeting }}
        </h1>
      </div>
      <p class="hero-subtitle">{{ data.subtitleText }}</p>
      <!-- AI 助理每日一句：首屏本地 tip 占位，AI 文案回来后交叉淡入替换 -->
      <div class="hero-assistant">
        <span class="assistant-badge" :class="`is-${data.assistantSource}`">
          <el-icon class="badge-icon"><MagicStick /></el-icon>
          {{ assistantBadge }}
        </span>
        <Transition name="assistant" mode="out-in">
          <p :key="data.assistantLine" class="assistant-text">{{ data.assistantLine }}</p>
        </Transition>
        <button
          type="button"
          class="assistant-refresh"
          :class="{ 'is-loading': data.assistantLoading }"
          title="换一句"
          aria-label="换一句"
          @click="data.loadGreeting(true)"
        >
          <el-icon><Refresh /></el-icon>
        </button>
      </div>
    </div>
    <div class="hero-decoration">
      <div class="geo-shape geo-square" />
      <div class="geo-shape geo-hexagon" />
      <div class="geo-shape geo-circle" />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { MagicStick, Refresh } from '@element-plus/icons-vue'

const props = defineProps({
  data: { type: Object, required: true }, // reactive 化的 useDashboardData 返回
})

const authStore = useAuthStore()

const assistantBadge = computed(() => ({
  ai: 'AI 助理',
  fallback: '今日提醒',
  tip: '每日一句',
}[props.data.assistantSource] || '每日一句'))
</script>

<style scoped>
/* 深色玻璃 Hero：右上金色光晕 + 半透明深底 + 实时 blur（全页仅 Hero 与
   待办提醒保留实时模糊，见 glass.css 头部性能约定），aurora 光斑透进来 */
.dashboard-hero {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  overflow: hidden;
  background:
    radial-gradient(120% 180% at 88% -10%, rgba(245, 203, 92, 0.16) 0%, rgba(245, 203, 92, 0) 55%),
    linear-gradient(135deg, rgba(22, 19, 16, 0.92) 0%, rgba(34, 29, 24, 0.86) 100%);
  -webkit-backdrop-filter: blur(var(--dash-glass-blur)) saturate(1.4);
  backdrop-filter: blur(var(--dash-glass-blur)) saturate(1.4);
  border: 1px solid var(--dash-glass-dark-border);
  border-radius: 16px;
  padding: 36px 40px;
  min-height: 140px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.08), var(--dash-glass-shadow);
}
@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
  .dashboard-hero {
    background: linear-gradient(135deg, var(--sidebar-bg-from), var(--sidebar-bg-to));
  }
}

.hero-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
  z-index: 2;
}

.hero-tag {
  font-family: var(--font-display);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--color-gold);
}

.hero-user-row {
  display: flex;
  align-items: center;
  gap: 14px;
}

.hero-avatar {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  overflow: hidden;
  flex-shrink: 0;
  border: 2px solid rgba(245, 203, 92, 0.3);
  box-shadow: 0 0 12px rgba(245, 203, 92, 0.15);
}
.hero-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.avatar-fallback {
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 700;
  color: var(--text-on-dark);
  background: linear-gradient(135deg, rgba(212, 175, 110, 0.4), rgba(160, 128, 64, 0.3));
}

.hero-greeting {
  font-family: var(--font-display);
  font-size: 28px;
  font-weight: 800;
  color: var(--text-on-dark);
  margin: 0;
  letter-spacing: -0.01em;
}

.hero-subtitle {
  font-family: var(--font-body);
  font-size: 14px;
  color: rgba(255, 255, 255, 0.6);
  margin: 0;
}

/* AI 助理问候条 */
.hero-assistant {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 14px;
  padding: 8px 12px 8px 14px;
  background: rgba(245, 203, 92, 0.08);
  border: 1px solid rgba(245, 203, 92, 0.15);
  border-radius: 10px;
  max-width: 640px;
  min-height: 38px;
}

.assistant-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  padding: 3px 8px;
  border-radius: 999px;
  font-family: var(--font-display);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: var(--ink-dark);
  background: var(--color-gold);
}
.assistant-badge.is-tip,
.assistant-badge.is-fallback {
  color: var(--color-gold);
  background: rgba(245, 203, 92, 0.12);
  border: 1px solid rgba(245, 203, 92, 0.25);
}
.badge-icon {
  font-size: 11px;
}

.assistant-text {
  flex: 1;
  min-width: 0;
  font-family: var(--font-body);
  font-size: 13px;
  color: rgba(245, 203, 92, 0.88);
  line-height: 1.55;
  margin: 0;
}

.assistant-refresh {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  flex-shrink: 0;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: rgba(245, 203, 92, 0.55);
  cursor: pointer;
  transition: transform 160ms var(--ease-out-strong), color 140ms ease, background-color 140ms ease;
}
.assistant-refresh:active {
  transform: scale(0.88);
}
@media (hover: hover) and (pointer: fine) {
  .assistant-refresh:hover {
    color: var(--color-gold);
    background: rgba(245, 203, 92, 0.1);
  }
}
.assistant-refresh:focus-visible {
  outline: 2px solid var(--color-gold);
  outline-offset: 1px;
}
.assistant-refresh.is-loading {
  animation: refreshSpin 0.9s linear infinite;
  pointer-events: none;
}
@keyframes refreshSpin {
  to { transform: rotate(360deg); }
}

/* 文案换场：交叉淡入 + 轻模糊遮罩（Emil：blur 弥合两态切换的生硬） */
.assistant-enter-active,
.assistant-leave-active {
  transition: opacity 220ms ease, transform 220ms var(--ease-out-strong), filter 220ms ease;
}
.assistant-enter-from {
  opacity: 0;
  transform: translateY(4px);
  filter: blur(2px);
}
.assistant-leave-to {
  opacity: 0;
  transform: translateY(-3px);
  filter: blur(2px);
}

@media (prefers-reduced-motion: reduce) {
  .assistant-refresh.is-loading {
    animation: none;
  }
  .assistant-enter-active,
  .assistant-leave-active {
    transition: opacity 160ms ease;
  }
  .assistant-enter-from,
  .assistant-leave-to {
    transform: none;
    filter: none;
  }
}

/* Hero 几何装饰 */
.hero-decoration {
  position: relative;
  width: 200px;
  height: 160px;
  flex-shrink: 0;
}

.geo-shape {
  position: absolute;
  border: 1px solid rgba(245, 203, 92, 0.15);
}

.geo-square {
  width: 80px;
  height: 80px;
  top: 20px;
  right: 40px;
  border-radius: 12px;
  animation: geoRotate 20s linear infinite;
}

.geo-hexagon {
  width: 50px;
  height: 50px;
  top: 60px;
  right: 10px;
  clip-path: polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%);
  background: rgba(245, 203, 92, 0.08);
  border: none;
  animation: geoBreathe 3s ease-in-out infinite;
}

.geo-circle {
  width: 100px;
  height: 100px;
  top: 10px;
  right: 60px;
  border-radius: 50%;
  animation: geoBreathe 4s ease-in-out infinite reverse;
}

@keyframes geoRotate {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}

@keyframes geoBreathe {
  0%, 100% { transform: scale(1); opacity: 0.5; }
  50%      { transform: scale(1.08); opacity: 1; }
}

@media (prefers-reduced-motion: reduce) {
  .geo-square, .geo-hexagon, .geo-circle {
    animation: none;
  }
}

@media (max-width: 767px) {
  .dashboard-hero {
    padding: 24px;
    flex-direction: column;
    align-items: flex-start;
    gap: 16px;
  }
  .hero-decoration {
    display: none;
  }
  .hero-greeting {
    font-size: 22px;
  }
}
</style>
