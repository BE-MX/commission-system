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
      ref="menu"
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
        :aria-label="item.title"
        tabindex="0"
        @keydown.enter.prevent.stop="activateMenuItem"
        @keydown.space.prevent.stop="activateMenuItem"
      >
        <el-icon><component :is="item.icon" /></el-icon>
        <template #title>
          <span>{{ item.title }}</span>
          <button
            v-if="!collapsed && item.name"
            v-permission="'task:write'"
            type="button"
            class="nav-add"
            data-quick-task-trigger
            :aria-label="`为「${item.title}」记任务`"
            :title="`为「${item.title}」记任务`"
            @click.stop.prevent="quickAdd($event, item)"
          >+</button>
        </template>
      </el-menu-item>

      <el-sub-menu
        v-for="group in visibleGroups"
        :key="group.key"
        :index="group.key"
        popper-class="ark-navigation-popup"
        :aria-label="group.title"
        aria-haspopup="menu"
        tabindex="0"
        :data-nav-group-trigger="group.key"
        @keydown.enter.self.prevent.stop="activateMenuGroup($event, group.key)"
        @keydown.space.self.prevent.stop="activateMenuGroup($event, group.key)"
        @keydown.esc.self.prevent.stop="closeKeyboardGroup($event, group.key)"
      >
        <template #title>
          <el-icon class="nav-group-icon">
            <component :is="group.icon" />
            <span v-if="group.iconBadge" class="nav-icon-badge">{{ group.iconBadge }}</span>
          </el-icon>
          <span>{{ group.title }}</span>
        </template>
        <template v-for="item in group.items" :key="item.path">
          <a
            v-if="item.external"
            class="el-menu-item external-item"
            :data-nav-group="group.key"
            @keydown.esc.prevent.stop="closeKeyboardGroup($event, group.key)"
            @focusout="leaveKeyboardGroup($event, group.key)"
            :href="item.path"
            target="_blank"
            rel="noopener"
          >
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.title }}</span>
            <el-icon class="ext-mark"><TopRight /></el-icon>
          </a>
          <el-menu-item v-else :index="item.path" :data-nav-group="group.key" tabindex="0"
            @keydown.enter.prevent.stop="activateMenuItem" @keydown.space.prevent.stop="activateMenuItem"
            @keydown.esc.prevent.stop="closeKeyboardGroup($event, group.key)" @focusout="leaveKeyboardGroup($event, group.key)">
            <el-icon><component :is="item.icon" /></el-icon>
            <template #title>
              <el-badge v-if="item.badge === 'domesticReviews'" :value="pendingReviews" :max="Number.MAX_SAFE_INTEGER" :hidden="pendingReviews === 0" class="nav-review-badge" :aria-label="`${item.title}，${pendingReviews}笔待审核`">
                <span>{{ item.title }}</span>
              </el-badge>
              <span v-else class="nav-document-label" :title="documentBadgeTitle(item)">{{ item.title }}<span v-if="documentAnomalies[item.anomalyDomain]?.has_anomaly" class="nav-document-anomaly" :aria-label="documentBadgeTitle(item)">!</span></span>
              <button
                v-if="!collapsed && item.name"
                v-permission="'task:write'"
                type="button"
                class="nav-add"
                data-quick-task-trigger
                :aria-label="`为「${item.title}」记任务`"
                :title="`为「${item.title}」记任务`"
                @click.stop.prevent="quickAdd($event, item)"
              >+</button>
            </template>
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
import { useDomesticReviewBadge } from './useDomesticReviewBadge'
import { useDocumentAnomalyBadge } from './useDocumentAnomalyBadge'
import { computed, nextTick, ref, watch } from 'vue'
import { Search, TopRight } from '@element-plus/icons-vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { MENU_GROUPS, NAV_ENTRIES } from '@/config/navigation'
import { useQuickTask } from '@/composables/useQuickTask'
import { filterNavigationSections, normalizeNavigationQuery } from './navigationSearch'

const props = defineProps({
  collapsed: { type: Boolean, default: false },
})

const pendingReviews = useDomesticReviewBadge()
const documentAnomalies = useDocumentAnomalyBadge()
function documentBadgeTitle(item) {
  const domain = documentAnomalies.value[item.anomalyDomain]
  if (!domain || domain.state === 'restricted') return ''
  if (domain.state === 'unavailable') return `${item.title}异常状态待核验${domain.has_anomaly ? '，保留上次异常提示' : ''}`
  return domain.has_anomaly ? `${item.title}存在异常单据，请查看核对` : ''
}
const route = useRoute()
const authStore = useAuthStore()
const { openQuickTask } = useQuickTask()

function quickAdd(event, item) {
  openQuickTask({ anchorEl: event.currentTarget, moduleKey: item.name, source: 'nav_quick' })
}

const menu = ref(null)
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
  .map(entry => ({ path: entry.path, name: entry.name, title: entry.menu.title ?? entry.title, icon: entry.menu.icon })))

const accessibleGroups = computed(() => Object.entries(MENU_GROUPS)
  .map(([key, group]) => {
    const items = NAV_ENTRIES
      .filter(entry => !entry.hideInMenu && entry.menu?.group === key && hasAccess(entry.menu))
      .slice()
      .sort((a, b) => (a.menu.order ?? 999) - (b.menu.order ?? 999))
      .map(entry => ({
        path: entry.path,
        name: entry.name,
        title: entry.menu.title ?? entry.title,
        icon: entry.menu.icon,
        external: entry.external === true,
        badge: entry.menu.badge,
        anomalyDomain: entry.menu.anomalyDomain,
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

// Keep Element Plus click routing/permission guards for keyboard activation too.
function activateMenuItem(event) {
  if (!event.repeat && event.target === event.currentTarget && !event.currentTarget.classList.contains('is-disabled')) event.currentTarget.click()
}
async function activateMenuGroup(event, key) {
  if (event.repeat || event.target !== event.currentTarget || event.currentTarget.classList.contains('is-disabled')) return
  const trigger = event.currentTarget
  if (trigger.getAttribute('aria-expanded') === 'true') {
    menu.value?.close(key)
    rememberClosedGroup(key)
    return
  }
  menu.value?.open(key)
  if (props.collapsed) {
    await nextTick()
    const firstItem = [...trigger.ownerDocument.querySelectorAll('[data-nav-group]')]
      .find(item => item.dataset.navGroup === key && item.getClientRects().length > 0)
    firstItem?.focus()
  }
}
function closeKeyboardGroup(event, key) {
  menu.value?.close(key)
  rememberClosedGroup(key)
  const trigger = [...menu.value?.$el.querySelectorAll('[data-nav-group-trigger]') || []]
    .find(item => item.dataset.navGroupTrigger === key)
  trigger?.focus()
}
function leaveKeyboardGroup(event, key) {
  if (!props.collapsed) return
  const target = event.relatedTarget
  if (target?.dataset.navGroup === key) return
  menu.value?.close(key)
  rememberClosedGroup(key)
}
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
.nav-document-label{position:relative;overflow:visible;margin-right:14px}
.nav-document-anomaly{position:absolute;right:-14px;top:-8px;width:14px;height:14px;display:grid;place-items:center;border-radius:50%;background:var(--color-gold);color:var(--sidebar-bg-from);font-size:10px;font-weight:800;line-height:1;box-shadow:0 0 6px var(--sidebar-glow-gold)}
.nav-review-badge { line-height: 20px; margin-right: 22px; }
.nav-review-badge :deep(.el-badge__content) { font-variant-numeric: tabular-nums; }

.nav-group-icon { position: relative; overflow: visible; }
.nav-icon-badge {
  position: absolute;
  right: -12px;
  bottom: -9px;
  z-index: 1;
  padding: 1px 3px;
  border: 1px solid var(--color-gold-muted);
  border-radius: 3px;
  background: var(--sidebar-bg-from);
  color: var(--color-gold);
  font-family: var(--font-body);
  font-size: 8px;
  font-style: normal;
  font-weight: 600;
  line-height: 10px;
  white-space: nowrap;
  pointer-events: none;
}

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
/* 任务中心：导航项悬浮 +（hover 高频出现，只做 120ms opacity + 轻微位移）。
   scoped 只给选择器最后一段 .nav-add 加作用域属性，祖先写 .el-menu-item 无需 :deep；
   el-menu-item 本身是 flex，按钮用 margin-left:auto 贴右，不需要改它的定位上下文。 */
.nav-add {
  display: grid;
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  margin-left: auto;
  place-items: center;
  border: 0;
  border-radius: 7px;
  background: var(--sidebar-glow-gold);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-gold) 35%, transparent);
  color: var(--color-gold);
  font: 600 15px/1 var(--font-display);
  cursor: pointer;
  opacity: 0;
  pointer-events: none;
  transform: translateX(4px);
  transition: opacity 120ms ease, transform 120ms cubic-bezier(0.23, 1, 0.32, 1), background-color 150ms ease;
}
.side-menu .el-menu-item:hover .nav-add,
.side-menu .el-menu-item:focus-within .nav-add,
.nav-add:focus-visible { opacity: 1; pointer-events: auto; transform: none; }
.nav-add:hover { background: color-mix(in srgb, var(--color-gold) 26%, transparent); }
.nav-add:active { transform: scale(0.94); }
.nav-add:focus-visible { outline: 2px solid var(--color-gold); outline-offset: 1px; }
.side-menu .el-menu-item.is-active .nav-add { color: var(--card-bg); background: color-mix(in srgb, var(--card-bg) 30%, transparent); box-shadow: none; }
@media (hover: none) { .nav-add { display: none; } }
@media (prefers-reduced-motion: reduce) { .nav-add { transition: none; transform: none; } }
</style>

<style>
.aside .el-menu-item:focus-visible, .aside .el-sub-menu:focus-visible > .el-sub-menu__title {
  outline: 2px solid var(--color-gold);
  outline-offset: -2px;
}
.ark-navigation-popup .el-menu-item:focus-visible {
  outline: 2px solid var(--color-gold);
  outline-offset: -2px;
}
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
