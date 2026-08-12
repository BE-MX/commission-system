<template>
  <el-aside :width="collapsed ? '68px' : '240px'" class="aside">
    <div class="sidebar-grain" aria-hidden="true"></div>

    <div class="logo-area">
      <img src="/logo.webp" alt="LeShine" class="logo-img" />
      <transition name="text-fade">
        <div v-show="!collapsed" class="logo-text-group">
          <span class="logo-text">LeShine</span>
          <span class="logo-sub">Ark Platform</span>
        </div>
      </transition>
    </div>

    <template v-if="!collapsed">
      <div class="menu-label">NAVIGATION</div>
      <div class="nav-search">
        <el-input
          v-model="searchQuery"
          :prefix-icon="Search"
          clearable
          placeholder="搜索导航"
          aria-label="搜索导航"
        />
      </div>
    </template>

    <el-menu
      :key="menuRenderKey"
      :default-active="route.meta.activeMenu || route.path"
      :default-openeds="defaultOpenGroupKeys"
      router
      :collapse="collapsed"
      class="side-menu"
      @open="rememberOpenedGroup"
      @close="rememberClosedGroup"
    >
      <el-menu-item
        v-for="item in topLevelItems"
        :key="item.path"
        :index="item.path"
      >
        <el-icon><component :is="item.icon" /></el-icon>
        <template #title>{{ item.title }}</template>
      </el-menu-item>

      <el-sub-menu
        v-for="group in visibleGroups"
        :key="group.key"
        :index="group.key"
      >
        <template #title>
          <el-icon><component :is="group.icon" /></el-icon>
          <span>{{ group.title }}</span>
        </template>
        <template v-for="item in group.items" :key="item.path">
          <a
            v-if="item.external"
            class="el-menu-item external-item"
            :href="item.path"
            target="_blank"
            rel="noopener"
          >
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.title }}</span>
            <el-icon class="ext-mark"><TopRight /></el-icon>
          </a>
          <el-menu-item v-else :index="item.path">
            <el-icon><component :is="item.icon" /></el-icon>
            <template #title>{{ item.title }}</template>
          </el-menu-item>
        </template>
      </el-sub-menu>

      <div v-if="hasNoMatches" class="nav-empty">
        <el-icon><Search /></el-icon>
        <span>未找到相关导航</span>
      </div>
    </el-menu>

    <div v-show="!collapsed" class="sidebar-bottom">
      <div class="env-badge">DEVELOPMENT</div>
    </div>
  </el-aside>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { Search, TopRight } from '@element-plus/icons-vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { MENU_GROUPS, NAV_ENTRIES } from '@/config/navigation'
import { filterNavigationSections, normalizeNavigationQuery } from './navigationSearch'

const props = defineProps({
  collapsed: { type: Boolean, default: false },
})

const route = useRoute()
const authStore = useAuthStore()
const searchQuery = ref('')
const openedGroupKeys = ref([])
const normalizedQuery = computed(() => normalizeNavigationQuery(searchQuery.value))

watch(() => props.collapsed, value => {
  if (value) searchQuery.value = ''
})

function hasAccess(perms) {
  if (!perms) return true
  if (perms.permission) return authStore.hasPermission(perms.permission)
  if (perms.anyPermission) return authStore.hasAnyPermission(perms.anyPermission)
  return true
}

const accessibleTopLevelItems = computed(() => NAV_ENTRIES
  .filter(entry => !entry.hideInMenu && entry.menu && !entry.menu.group && hasAccess(entry.menu))
  .slice()
  .sort((a, b) => (a.menu.order ?? 999) - (b.menu.order ?? 999))
  .map(entry => ({ path: entry.path, title: entry.menu.title ?? entry.title, icon: entry.menu.icon })))

const accessibleGroups = computed(() => Object.entries(MENU_GROUPS)
  .map(([key, group]) => {
    const items = NAV_ENTRIES
      .filter(entry => !entry.hideInMenu && entry.menu?.group === key && hasAccess(entry.menu))
      .slice()
      .sort((a, b) => (a.menu.order ?? 999) - (b.menu.order ?? 999))
      .map(entry => ({
        path: entry.path,
        title: entry.menu.title ?? entry.title,
        icon: entry.menu.icon,
        external: entry.external === true,
      }))
    return { key, ...group, items }
  })
  .filter(group => hasAccess(group) && group.items.length > 0))

const filteredNavigation = computed(() => filterNavigationSections(
  accessibleTopLevelItems.value,
  accessibleGroups.value,
  normalizedQuery.value,
))
const topLevelItems = computed(() => filteredNavigation.value.topLevelItems)
const visibleGroups = computed(() => filteredNavigation.value.groups)

const defaultOpenGroupKeys = computed(() => (
  normalizedQuery.value ? visibleGroups.value.map(group => group.key) : openedGroupKeys.value
))
const menuRenderKey = computed(() => `navigation-${normalizedQuery.value}`)
const hasNoMatches = computed(() => (
  Boolean(normalizedQuery.value)
  && topLevelItems.value.length === 0
  && visibleGroups.value.length === 0
))

function rememberOpenedGroup(key) {
  if (normalizedQuery.value || openedGroupKeys.value.includes(key)) return
  openedGroupKeys.value = [...openedGroupKeys.value, key]
}

function rememberClosedGroup(key) {
  if (normalizedQuery.value) return
  openedGroupKeys.value = openedGroupKeys.value.filter(item => item !== key)
}
</script>

<style scoped>
.aside {
  background: linear-gradient(180deg, var(--sidebar-glass-from) 0%, var(--sidebar-glass-to) 100%);
  border-right: 1px solid rgba(255, 255, 255, 0.06);
  box-shadow: 4px 0 24px rgba(20, 18, 16, 0.25);
  transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  position: relative;
  z-index: 10;
}
.aside::before,
.aside::after {
  content: "";
  position: absolute;
  border-radius: 50%;
  pointer-events: none;
}
.aside::before {
  width: 280px;
  height: 280px;
  top: -90px;
  right: -110px;
  background: radial-gradient(circle, var(--sidebar-glow-gold) 0%, rgba(245, 203, 92, 0) 68%);
}
.aside::after {
  width: 300px;
  height: 300px;
  bottom: -110px;
  left: -130px;
  background: radial-gradient(circle, var(--sidebar-glow-slate) 0%, rgba(107, 140, 186, 0) 68%);
}
.sidebar-grain {
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0.035;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
}
.logo-area {
  height: 60px;
  display: flex;
  align-items: center;
  padding: 0 16px;
  gap: 12px;
  flex-shrink: 0;
  position: relative;
  z-index: 1;
}
.logo-img { width: 36px; height: 36px; border-radius: 8px; object-fit: cover; flex-shrink: 0; }
.logo-text-group { display: flex; flex-direction: column; white-space: nowrap; }
.logo-text {
  font-family: var(--font-display);
  color: var(--color-gold);
  font-size: 17px;
  font-weight: 800;
  letter-spacing: 0.04em;
  line-height: 1;
}
.logo-sub {
  margin-top: 3px;
  color: rgba(255, 255, 255, 0.4);
  font-family: var(--font-display);
  font-size: 9px;
  font-weight: 500;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.menu-label {
  padding: 20px 20px 8px;
  color: rgba(255, 255, 255, 0.32);
  font-family: var(--font-display);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  position: relative;
  z-index: 1;
}
.nav-search { padding: 0 12px 10px; position: relative; z-index: 1; }
.nav-search :deep(.el-input__wrapper) {
  min-height: 34px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.07);
  box-shadow: none;
  transition: border-color 0.2s ease, background-color 0.2s ease, box-shadow 0.2s ease;
}
.nav-search :deep(.el-input__wrapper:hover) { background: rgba(255, 255, 255, 0.1); }
.nav-search :deep(.el-input__wrapper.is-focus) {
  border-color: rgba(245, 203, 92, 0.55);
  background: rgba(255, 255, 255, 0.11);
  box-shadow: 0 0 0 3px rgba(212, 148, 28, 0.12);
}
.nav-search :deep(.el-input__inner) { color: rgba(255, 255, 255, 0.9); font-size: 12px; }
.nav-search :deep(.el-input__inner::placeholder),
.nav-search :deep(.el-input__prefix),
.nav-search :deep(.el-input__suffix) { color: rgba(255, 255, 255, 0.38); }
.side-menu {
  border-right: none;
  background: transparent;
  flex: 1;
  overflow-y: auto;
  padding: 0 8px;
  position: relative;
  z-index: 1;
}
.side-menu:not(.el-menu--collapse) { width: 240px; }
:deep(.el-menu) { background-color: transparent; --el-menu-hover-bg-color: transparent; }
:deep(.el-menu-item),
:deep(.el-sub-menu__title) {
  color: rgba(255, 255, 255, 0.55);
  height: 42px;
  line-height: 42px;
  margin: 1px 0;
  border-radius: 10px;
  font-family: var(--font-display);
  font-size: 13px;
  font-weight: 500;
  transition: background-color 0.2s ease, color 0.2s ease, box-shadow 0.2s ease;
  position: relative;
}
:deep(.el-menu-item:hover),
:deep(.el-sub-menu__title:hover) { background-color: rgba(255, 255, 255, 0.08); color: rgba(255, 255, 255, 0.92); }
:deep(.el-menu-item.is-active) {
  color: var(--card-bg);
  background: linear-gradient(135deg, var(--color-gold), var(--color-primary));
  box-shadow: 0 4px 14px rgba(212, 148, 28, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.35);
  font-weight: 600;
}
:deep(.el-menu-item.is-active .el-icon) { color: var(--card-bg); }
:deep(.el-menu-item.is-active:hover) {
  color: var(--card-bg);
  background: linear-gradient(135deg, var(--color-gold), var(--color-primary-hover));
}
:deep(.el-sub-menu.is-active > .el-sub-menu__title) { color: var(--color-gold); font-weight: 600; }
:deep(.el-sub-menu .el-menu-item) { padding-left: 52px !important; font-size: 13px; }
:deep(a.external-item) { text-decoration: none; }
:deep(.ext-mark) { font-size: 11px; opacity: 0.45; margin-left: 4px; }
.nav-empty {
  display: flex;
  min-height: 120px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: rgba(255, 255, 255, 0.38);
  font-size: 12px;
}
.nav-empty .el-icon { font-size: 20px; }
.sidebar-bottom {
  padding: 16px;
  border-top: 1px solid rgba(245, 203, 92, 0.1);
  flex-shrink: 0;
  position: relative;
  z-index: 1;
}
.env-badge {
  padding: 4px 8px;
  border-radius: 4px;
  color: var(--color-gold);
  background: rgba(245, 203, 92, 0.12);
  font-family: var(--font-display);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-align: center;
}
.text-fade-enter-active,
.text-fade-leave-active { transition: opacity 0.2s ease; }
.text-fade-enter-from,
.text-fade-leave-to { opacity: 0; }

@media (prefers-reduced-motion: reduce) {
  .aside,
  :deep(.el-menu-item),
  :deep(.el-sub-menu__title),
  .nav-search :deep(.el-input__wrapper) { transition: none; }
}
</style>

<style>
.el-menu--popup {
  background: rgba(34, 37, 46, 0.92) !important;
  backdrop-filter: blur(var(--dash-glass-blur)) saturate(1.5);
  -webkit-backdrop-filter: blur(var(--dash-glass-blur)) saturate(1.5);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  box-shadow: 0 12px 32px rgba(20, 18, 16, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.06);
  padding: 4px;
}
.el-menu--popup .el-menu-item { color: rgba(255, 255, 255, 0.55); border-radius: 8px; }
.el-menu--popup .el-menu-item:hover { background-color: rgba(255, 255, 255, 0.08); color: rgba(255, 255, 255, 0.92); }
.el-menu--popup .el-menu-item.is-active {
  color: var(--card-bg);
  background: linear-gradient(135deg, var(--color-gold), var(--color-primary));
  box-shadow: 0 4px 14px rgba(212, 148, 28, 0.35);
}
.el-menu--popup a.el-menu-item { text-decoration: none; }
.el-menu--popup .ext-mark { margin-left: 4px; font-size: 11px; opacity: 0.45; }
</style>
