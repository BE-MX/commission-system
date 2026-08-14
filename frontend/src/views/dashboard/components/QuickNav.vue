<template>
  <section v-if="items.length > 0" class="quick-nav" aria-label="最近使用">
    <div class="quick-nav-label">
      <el-icon><Clock /></el-icon>
      <span>最近使用</span>
    </div>
    <div class="quick-nav-track">
      <button
        v-for="(item, index) in items"
        :key="item.name"
        type="button"
        class="quick-chip"
        :style="{ '--chip-index': index }"
        @click="go(item)"
      >
        <el-icon class="chip-icon"><component :is="item.icon" /></el-icon>
        <span class="chip-title">{{ item.title }}</span>
        <el-icon class="chip-arrow"><TopRight /></el-icon>
      </button>
    </div>
  </section>
</template>

<script setup>
/**
 * 最近使用 — 快跳芯片条。
 * 数据源是 router afterEach 写入的 localStorage 记录（utils/recentNav.js），
 * 这里只做：按 navigation.js 注册表补图标/标题 → 权限过滤 → 取前 8 条。
 * Dashboard 被 KeepAlive 缓存，回切时用 onActivated 刷新列表。
 */
import { onActivated, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Clock, TopRight } from '@element-plus/icons-vue'
import { NAV_ENTRIES } from '@/config/navigation'
import { getRecentNav } from '@/utils/recentNav'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const items = ref([])

const ENTRY_BY_NAME = new Map(NAV_ENTRIES.map(entry => [entry.name, entry]))

function hasAccess(perms) {
  if (!perms) return true
  if (perms.permission) return authStore.hasPermission(perms.permission)
  if (perms.anyPermission) return authStore.hasAnyPermission(perms.anyPermission)
  return true
}

function refresh() {
  items.value = getRecentNav()
    .map(record => {
      const entry = ENTRY_BY_NAME.get(record.name)
      if (!entry?.menu || !hasAccess(entry.menu) || !hasAccess(entry)) return null
      return {
        name: entry.name,
        path: record.path || entry.path,
        title: entry.menu.title ?? entry.title,
        icon: entry.menu.icon,
      }
    })
    .filter(Boolean)
    .slice(0, 8)
}

function go(item) {
  router.push(item.path)
}

onMounted(refresh)
onActivated(refresh)
</script>

<style scoped>
.quick-nav {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 4px 2px;
}

.quick-nav-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  font-family: var(--font-display);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-secondary);
}

.quick-nav-track {
  display: flex;
  gap: 10px;
  overflow-x: auto;
  padding: 4px 2px;
  scrollbar-width: none;
}
.quick-nav-track::-webkit-scrollbar {
  display: none;
}

.quick-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  padding: 9px 14px;
  border: 1px solid var(--dash-glass-border);
  border-radius: 999px;
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-highlight), var(--card-shadow);
  color: var(--text-primary);
  font-family: var(--font-body);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition:
    transform 160ms var(--ease-out-strong),
    box-shadow 160ms ease,
    border-color 160ms ease;
  /* 入场：从下方 8px 浮入，30ms 级联（Emil：chip 是高频元素，快而轻） */
  animation: chipIn 220ms var(--ease-out-strong) both;
  animation-delay: calc(var(--chip-index) * 30ms);
}
.quick-chip:active {
  transform: scale(0.96);
}
@media (hover: hover) and (pointer: fine) {
  .quick-chip:hover {
    transform: translateY(-2px);
    border-color: var(--color-primary-glow);
    box-shadow: var(--dash-glass-highlight), var(--card-shadow-hover);
  }
  .quick-chip:hover .chip-arrow {
    opacity: 1;
    transform: translate(0, 0);
  }
}
.quick-chip:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

.chip-icon {
  font-size: 15px;
  color: var(--color-gold-muted);
}

.chip-arrow {
  font-size: 12px;
  color: var(--color-primary);
  opacity: 0;
  transform: translate(-3px, 3px);
  transition: opacity 140ms ease, transform 160ms var(--ease-out-strong);
}

@keyframes chipIn {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}

@media (prefers-reduced-motion: reduce) {
  .quick-chip {
    animation: chipFade 180ms ease both;
  }
  @keyframes chipFade {
    from { opacity: 0; }
    to   { opacity: 1; }
  }
}

@media (max-width: 767px) {
  .quick-nav {
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
  }
}
</style>
