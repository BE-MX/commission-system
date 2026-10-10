<template>
  <el-container class="main-layout">
    <SidebarNavigation v-if="!isNarrow" :collapsed="isCollapse" />
    <el-drawer v-else v-model="mobileNavigationOpen" direction="ltr" size="280px"
      title="导航" class="mobile-navigation" append-to-body>
      <SidebarNavigation :collapsed="false" />
    </el-drawer>

    <el-container class="right-container">
      <div class="navigation-chrome">
        <el-header class="header">
          <div class="header-left">
            <button
              class="collapse-toggle"
              type="button"
              :aria-label="isNarrow ? '打开导航菜单' : (isCollapse ? '展开导航栏' : '收起导航栏')"
              :aria-expanded="isNarrow ? mobileNavigationOpen : !isCollapse"
              @click="isNarrow ? mobileNavigationOpen = true : isCollapse = !isCollapse"
            >
              <Fold v-if="!isCollapse" />
              <Expand v-else />
            </button>
            <div class="header-title-group">
              <h1 class="page-title">{{ route.meta.title || '工作台' }}</h1>
            </div>
          </div>
          <div class="header-right">
            <GlassButton v-permission="'task:write'" class="header-quick-task" size="sm" left-icon="EditPen" data-quick-task-trigger @click="openHeaderQuickTask">记任务</GlassButton>
            <AnnouncementBell />
            <div class="header-badge">莱莎发制品</div>
            <el-dropdown trigger="click" @command="handleUserCommand">
              <div class="user-trigger">
                <img
                  v-if="authStore.user?.avatar_url"
                  :src="authStore.user.avatar_url"
                  class="header-avatar"
                  alt="avatar"
                />
                <el-icon v-else><UserFilled /></el-icon>
                <span>{{ authStore.user?.real_name || '用户' }}</span>
                <el-icon class="arrow"><ArrowDown /></el-icon>
              </div>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="profile"><el-icon><User /></el-icon> 个人设置</el-dropdown-item>
                  <el-dropdown-item command="password"><el-icon><Key /></el-icon> 修改密码</el-dropdown-item>
                  <el-dropdown-item divided command="logout"><el-icon><SwitchButton /></el-icon> 退出登录</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </el-header>

        <NavigationTabs
          :tabs="tabs"
          :active-key="activeKey"
          @select="selectTab"
          @close="closeTab"
        />
      </div>

      <el-main
        class="main-content"
        role="tabpanel"
        :id="getTabPanelId(activeKey)"
        :aria-labelledby="getTabButtonId(activeKey)"
        tabindex="0"
      >
        <div class="page-wrapper">
          <router-view v-slot="{ Component, route: viewRoute }">
            <transition name="page" mode="out-in">
              <KeepAlive :include="cachedTabNames">
                <component
                  :is="getCachedView(Component, viewRoute)"
                  :key="getRouteCacheKey(viewRoute)"
                />
              </KeepAlive>
            </transition>
          </router-view>
        </div>
      </el-main>
    </el-container>
    <QuickTaskPopover />
  </el-container>
</template>

<script setup>
import {
  computed,
  defineComponent,
  h,
  markRaw,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import GlassButton from '@/components/GlassButton.vue'
import QuickTaskPopover from '@/components/task/QuickTaskPopover.vue'
import AnnouncementBell from '@/components/announcement/AnnouncementBell.vue'
import { useQuickTask } from '@/composables/useQuickTask'
import { NAV_ENTRIES } from '@/config/navigation'
import NavigationTabs from './NavigationTabs.vue'
import SidebarNavigation from './SidebarNavigation.vue'
import { useNavigationTabs } from './navigationTabs'
import { getRouteTabKey, getTabButtonId, getTabPanelId } from './navigationTabState'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const { openQuickTask } = useQuickTask()

// 预填当前页面对应的模块：详情等隐藏页按 activeMenu 找回它所属的导航页；浮层会校验模块是否在注册表里
function currentModuleKey() {
  const menuPath = route.meta.activeMenu || route.path
  return NAV_ENTRIES.find(entry => entry.menu && entry.path === menuPath)?.name ?? route.name ?? null
}

function openHeaderQuickTask(event) {
  openQuickTask({ anchorEl: event?.currentTarget, moduleKey: currentModuleKey(), source: 'header_quick' })
}
const mobileQuery = globalThis.matchMedia?.('(max-width: 640px)')
const isNarrow = ref(mobileQuery?.matches ?? false)
const desktopCollapse = ref(false)
const mobileNavigationOpen = ref(false)
const isCollapse = computed({
  get: () => isNarrow.value || desktopCollapse.value,
  set: value => {
    if (!isNarrow.value) desktopCollapse.value = value
  },
})
const {
  tabs,
  activeKey,
  selectTab,
  closeTab,
  getRouteCacheKey,
  getTabCacheName,
  cachedTabNames,
} = useNavigationTabs(route, router)
const cachedViews = new Map()

function getCachedView(viewComponent, viewRoute) {
  const cacheName = getTabCacheName(getRouteTabKey(viewRoute))
  if (!cachedViews.has(cacheName)) {
    cachedViews.set(cacheName, markRaw(defineComponent({
      name: cacheName,
      setup: () => () => h(viewComponent),
    })))
  }
  return cachedViews.get(cacheName)
}

watch(cachedTabNames, names => {
  const activeNames = new Set(names)
  for (const name of cachedViews.keys()) {
    if (!activeNames.has(name)) cachedViews.delete(name)
  }
}, { flush: 'post' })

function onNarrowChange(event) {
  isNarrow.value = event.matches
  mobileNavigationOpen.value = false
}
watch(() => route.fullPath, () => { mobileNavigationOpen.value = false })

onMounted(() => mobileQuery?.addEventListener('change', onNarrowChange))
onBeforeUnmount(() => mobileQuery?.removeEventListener('change', onNarrowChange))

function handleUserCommand(command) {
  if (command === 'profile' || command === 'password') router.push('/profile')
  else if (command === 'logout') authStore.logout()
}
</script>

<style scoped>
.main-layout { height: 100vh; height: 100dvh; }
.right-container {
  position: relative;
  min-width: 0;
  flex-direction: column;
  --navigation-chrome-height: calc(var(--header-height) + 45px);
  background: var(--dash-glass-nav-backdrop);
}
/* Both bars float above the content scrollport, sharing one real backdrop blur. */
.navigation-chrome {
  position: absolute;
  inset: 0 0 auto;
  z-index: 5;
  flex-shrink: 0;
  min-width: 0;
  background: var(--dash-glass-nav-fallback);
  border-bottom: 1px solid var(--dash-glass-nav-border);
  box-shadow: var(--dash-glass-nav-shadow), var(--dash-glass-highlight);
}
@supports ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
  .navigation-chrome {
    background: var(--dash-glass-nav-bg);
    -webkit-backdrop-filter: blur(var(--dash-glass-blur)) saturate(1.4);
    backdrop-filter: blur(var(--dash-glass-blur)) saturate(1.4);
  }
}
@media (prefers-reduced-transparency: reduce) {
  .navigation-chrome {
    background: var(--dash-glass-nav-fallback);
    -webkit-backdrop-filter: none;
    backdrop-filter: none;
  }
}
.header {
  display: flex;
  height: var(--header-height);
  flex-shrink: 0;
  align-items: center;
  justify-content: space-between;
  padding: 0 28px;
  border-bottom: 1px solid var(--dash-glass-nav-divider);
  background: transparent;
}
.header-left { display: flex; min-width: 0; align-items: center; gap: 16px; }
.header-title-group { min-width: 0; }
.collapse-toggle {
  display: flex;
  width: 32px;
  flex-shrink: 0;
  height: 32px;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-secondary);
  background: var(--card-bg);
  font-size: 16px;
  cursor: pointer;
  transition: border-color 0.2s ease, color 0.2s ease, background-color 0.2s ease;
}
.collapse-toggle:hover {
  border-color: var(--color-primary);
  color: var(--color-primary-text);
  background: var(--color-primary-light);
}
.collapse-toggle:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.page-title {
  margin: 0;
  color: var(--text-primary);
  font-family: var(--font-display);
  font-size: 17px;
  font-weight: 700;
}
.header-right { display: flex; align-items: center; gap: 12px; }
.header-badge {
  padding: 5px 12px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  color: var(--text-secondary);
  background: var(--color-gold-soft);
  font-family: var(--font-display);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
}
.user-trigger {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 8px;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: background-color 0.2s ease;
}
.user-trigger:hover { background: var(--color-gold-soft); }
.header-avatar {
  width: 28px;
  height: 28px;
  border: 1px solid var(--border-color);
  border-radius: 50%;
  object-fit: cover;
}
.user-trigger .arrow { margin-left: 2px; font-size: 10px; }
.main-content {
  min-height: 0;
  padding: 24px 28px;
  padding-top: calc(var(--navigation-chrome-height) + 24px);
  scroll-padding-top: calc(var(--navigation-chrome-height) + 24px);
  background: transparent;
}
.page-wrapper { max-width: 1440px; }
.page-wrapper > * { min-width: 0; max-width: 100%; box-sizing: border-box; }
.page-enter-active { transition: opacity 120ms ease; }
.page-leave-active { transition: opacity 80ms ease; }
.page-enter-from { opacity: 0; }
.page-leave-to { opacity: 0; }

@media (max-width: 640px) {
  .header { padding: 0 10px; }
  .header-left { gap: 8px; }
  .header-badge { display: none; }
  .header-quick-task { display: none; }
  .main-content {
    padding: 12px 10px;
    padding-top: calc(var(--navigation-chrome-height) + 12px);
    scroll-padding-top: calc(var(--navigation-chrome-height) + 12px);
  }
  .page-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .user-trigger { padding-inline: 6px; }
  .user-trigger span,
  .user-trigger .arrow { display: none; }
}
@media (prefers-reduced-motion: reduce) {
  .collapse-toggle,
  .user-trigger,
  .page-enter-active,
  .page-leave-active { transition: none; }
  .page-enter-from { transform: none; }
}
</style>

<style>
.main-layout :fullscreen { --navigation-chrome-height: 0px; }
.mobile-navigation.el-drawer.ltr { border-radius: 0 16px 16px 0 !important; }
.mobile-navigation .el-drawer__body { display: flex; padding: 0; }
.mobile-navigation .aside { width: 100% !important; }
</style>
