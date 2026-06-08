<template>
  <header class="db-topbar">
    <!-- 左侧：状态点 + 标题 -->
    <div class="db-topbar__left">
      <span class="db-topbar__dot"></span>
      <span class="db-topbar__title">生产订单可视化看板</span>
    </div>

    <!-- 中间：实时时钟 -->
    <div class="db-topbar__center">
      <span class="db-topbar__clock">{{ clockStr }}</span>
    </div>

    <!-- 右侧：主题切换 -->
    <div class="db-topbar__right">
      <button class="db-topbar__theme-btn" @click="toggleTheme" :title="isDark ? '切换浅色主题' : '切换深色主题'">
        <span class="db-topbar__theme-icon">{{ isDark ? '☀️' : '🌙' }}</span>
        <span class="db-topbar__theme-label">{{ isDark ? '浅色' : '深色' }}</span>
      </button>
    </div>
  </header>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useDashboardTheme } from '@/views/production/composables/useDashboardTheme'

const { isDark, toggleTheme } = useDashboardTheme()

const clockStr = ref('')

function formatClock() {
  const now = new Date()
  const mm = String(now.getMonth() + 1).padStart(2, '0')
  const dd = String(now.getDate()).padStart(2, '0')
  const hh = String(now.getHours()).padStart(2, '0')
  const mi = String(now.getMinutes()).padStart(2, '0')
  const ss = String(now.getSeconds()).padStart(2, '0')
  clockStr.value = `${mm}-${dd} ${hh}:${mi}:${ss}`
}

let timer = null
onMounted(() => {
  formatClock()
  timer = setInterval(formatClock, 1000)
})
onUnmounted(() => {
  clearInterval(timer)
})
</script>

<style scoped>
.db-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 56px;
  padding: 0 24px;
  background: var(--db-topbar-bg);
  border-bottom: 1px solid var(--db-border);
  position: sticky;
  top: 0;
  z-index: 100;
  flex-shrink: 0;
}

/* 左侧 */
.db-topbar__left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 220px;
}

.db-topbar__dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--db-accent-green);
  box-shadow: 0 0 6px var(--db-accent-green);
  animation: db-blink 1.4s ease-in-out infinite;
  flex-shrink: 0;
}

@keyframes db-blink {
  0%, 100% { opacity: 1; box-shadow: 0 0 6px var(--db-accent-green); }
  50%       { opacity: 0.35; box-shadow: 0 0 2px var(--db-accent-green); }
}

.db-topbar__title {
  font-size: 16px;
  font-weight: 700;
  color: var(--db-text-primary);
  letter-spacing: 0.04em;
  white-space: nowrap;
}

/* 中间 */
.db-topbar__center {
  flex: 1;
  display: flex;
  justify-content: center;
}

.db-topbar__clock {
  font-size: 15px;
  font-family: 'SF Mono', 'Fira Mono', monospace;
  color: var(--db-text-secondary);
  letter-spacing: 0.08em;
  background: var(--db-card-bg);
  border: 1px solid var(--db-border);
  padding: 3px 14px;
  border-radius: 20px;
}

/* 右侧 */
.db-topbar__right {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  min-width: 120px;
}

.db-topbar__theme-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--db-card-bg);
  border: 1px solid var(--db-border);
  border-radius: 20px;
  padding: 5px 14px;
  cursor: pointer;
  color: var(--db-text-secondary);
  font-size: 13px;
  transition: background 0.2s, border-color 0.2s, color 0.2s;
}

.db-topbar__theme-btn:hover {
  background: var(--db-hover-bg);
  border-color: var(--db-accent-blue);
  color: var(--db-text-primary);
}

.db-topbar__theme-icon {
  font-size: 15px;
  line-height: 1;
}

.db-topbar__theme-label {
  white-space: nowrap;
}
</style>
