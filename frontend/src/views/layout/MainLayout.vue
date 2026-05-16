<template>
  <el-container class="main-layout">
    <el-aside :width="isCollapse ? '68px' : '240px'" class="aside">
      <!-- Grain overlay on sidebar -->
      <div class="sidebar-grain"></div>

      <div class="logo-area">
        <img src="/logo.webp" alt="LeShine" class="logo-img" />
        <transition name="text-fade">
          <div v-show="!isCollapse" class="logo-text-group">
            <span class="logo-text">LeShine</span>
            <span class="logo-sub">Ark Platform</span>
          </div>
        </transition>
      </div>

      <div class="menu-label" v-show="!isCollapse">NAVIGATION</div>

      <el-menu
        :default-active="route.path"
        router
        :collapse="isCollapse"
        class="side-menu"
      >
        <!-- 顶级菜单项 (Dashboard 等无分组的入口) -->
        <el-menu-item
          v-for="item in topLevelItems"
          :key="item.path"
          :index="item.path"
        >
          <el-icon><component :is="item.icon" /></el-icon>
          <template #title>{{ item.title }}</template>
        </el-menu-item>

        <!-- 分组菜单 -->
        <el-sub-menu
          v-for="group in visibleGroups"
          :key="group.key"
          :index="group.key"
        >
          <template #title>
            <el-icon><component :is="group.icon" /></el-icon>
            <span>{{ group.title }}</span>
          </template>
          <el-menu-item
            v-for="item in group.items"
            :key="item.path"
            :index="item.path"
          >
            <el-icon><component :is="item.icon" /></el-icon>
            <template #title>{{ item.title }}</template>
          </el-menu-item>
        </el-sub-menu>
      </el-menu>

      <div class="sidebar-bottom" v-show="!isCollapse">
        <div class="env-badge">DEVELOPMENT</div>
      </div>
    </el-aside>

    <el-container class="right-container">
      <el-header class="header">
        <div class="header-left">
          <button class="collapse-toggle" @click="isCollapse = !isCollapse">
            <Fold v-if="!isCollapse" />
            <Expand v-else />
          </button>
          <div class="header-title-group">
            <h1 class="page-title">{{ route.meta.title || '工作台' }}</h1>
          </div>
        </div>
        <div class="header-right">
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
      <el-main class="main-content">
        <div class="page-wrapper">
          <router-view v-slot="{ Component }">
            <transition name="page" mode="out-in">
              <component :is="Component" />
            </transition>
          </router-view>
        </div>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { NAV_ENTRIES, MENU_GROUPS } from '@/config/navigation'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const isCollapse = ref(false)

// 权限策略检查 — 支持 permission(单权限) 与 anyPermission(任一即可)
function hasAccess(perms) {
  if (!perms) return true
  if (perms.permission) return authStore.hasPermission(perms.permission)
  if (perms.anyPermission) return authStore.hasAnyPermission(perms.anyPermission)
  return true
}

// 顶级菜单项 (menu 字段存在但无 group, 例如 Dashboard)
const topLevelItems = computed(() => {
  return NAV_ENTRIES
    .filter(e => !e.hideInMenu && e.menu && !e.menu.group && hasAccess(e.menu))
    .slice()
    .sort((a, b) => (a.menu.order ?? 999) - (b.menu.order ?? 999))
    .map(e => ({ path: e.path, title: e.menu.title ?? e.title, icon: e.menu.icon }))
})

// 分组菜单 — 分组本身权限不通过或无可见子项即隐藏
const visibleGroups = computed(() => {
  return Object.entries(MENU_GROUPS)
    .map(([key, group]) => {
      const items = NAV_ENTRIES
        .filter(e => !e.hideInMenu && e.menu?.group === key && hasAccess(e.menu))
        .slice()
        .sort((a, b) => (a.menu.order ?? 999) - (b.menu.order ?? 999))
        .map(e => ({ path: e.path, title: e.menu.title ?? e.title, icon: e.menu.icon }))
      return { key, ...group, items }
    })
    .filter(group => hasAccess(group) && group.items.length > 0)
})

function handleUserCommand(cmd) {
  if (cmd === 'profile') router.push('/profile')
  else if (cmd === 'password') router.push('/profile')
  else if (cmd === 'logout') authStore.logout()
}
</script>

<style scoped>
.main-layout {
  height: 100vh;
}

/* ===== Sidebar ===== */
.aside {
  background: linear-gradient(180deg, var(--sidebar-bg-from) 0%, var(--sidebar-bg-to) 100%);
  transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  position: relative;
  z-index: 10;
}

.sidebar-grain {
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0.035;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
}

/* Logo */
.logo-area {
  height: 60px;
  display: flex;
  align-items: center;
  padding: 0 16px;
  gap: 12px;
  flex-shrink: 0;
  position: relative;
}
.logo-img {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  object-fit: cover;
  flex-shrink: 0;
}
.logo-text-group {
  display: flex;
  flex-direction: column;
  white-space: nowrap;
}
.logo-text {
  font-family: var(--font-display);
  color: var(--color-gold);
  font-size: 17px;
  font-weight: 800;
  letter-spacing: 0.04em;
  line-height: 1;
}
.logo-sub {
  font-family: var(--font-display);
  color: #5C5550;
  font-size: 9px;
  font-weight: 500;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-top: 3px;
}

/* Menu section label */
.menu-label {
  font-family: var(--font-display);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: #3D3832;
  padding: 20px 20px 8px;
  text-transform: uppercase;
}

/* Menu */
.side-menu {
  border-right: none;
  background: transparent;
  flex: 1;
  overflow-y: auto;
  padding: 0 8px;
}
.side-menu:not(.el-menu--collapse) {
  width: 240px;
}

:deep(.el-menu) {
  background-color: transparent;
  --el-menu-hover-bg-color: transparent;
}
:deep(.el-menu-item),
:deep(.el-sub-menu__title) {
  color: #9C9590;
  height: 42px;
  line-height: 42px;
  margin: 1px 0;
  border-radius: 10px;
  font-family: var(--font-display);
  font-size: 13px;
  font-weight: 500;
  transition: all 0.2s ease;
  position: relative;
}
:deep(.el-menu-item:hover),
:deep(.el-sub-menu__title:hover) {
  background-color: rgba(245,203,92,0.04);
  color: #D4C4A8;
}

/* Active state: gold left accent bar */
:deep(.el-menu-item.is-active) {
  color: var(--color-gold);
  background: rgba(245,203,92,0.08);
  font-weight: 600;
}
:deep(.el-menu-item.is-active::before) {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: var(--color-gold);
  box-shadow: 0 0 8px rgba(245,203,92,0.4);
}
:deep(.el-sub-menu.is-active > .el-sub-menu__title) {
  color: #D4C4A8;
}
:deep(.el-sub-menu .el-menu-item) {
  padding-left: 52px !important;
  font-size: 13px;
}
:deep(.el-menu--popup) {
  background-color: #1E1B18;
  border: 1px solid #332E28;
  border-radius: 10px;
  padding: 4px;
}

/* Sidebar bottom */
.sidebar-bottom {
  padding: 16px;
  border-top: 1px solid rgba(245,203,92,0.06);
  flex-shrink: 0;
}
.env-badge {
  font-family: var(--font-display);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.1em;
  color: var(--color-gold);
  background: rgba(245,203,92,0.08);
  padding: 4px 8px;
  border-radius: 4px;
  text-align: center;
}

/* ===== Header ===== */
.right-container {
  background: var(--page-bg);
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  padding: 0 28px;
  height: var(--header-height);
  border-bottom: 1px solid var(--border-color);
  z-index: 5;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}
.collapse-toggle {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: 1px solid var(--border-color);
  background: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--text-secondary);
  transition: all 0.2s ease;
  font-size: 16px;
}
.collapse-toggle:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-light);
}.page-title {
  font-family: var(--font-display);
  font-size: 17px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.header-badge {
  font-family: var(--font-display);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--text-secondary);
  padding: 5px 12px;
  background: #F5F2EE;
  border-radius: 6px;
  border: 1px solid var(--border-color);
}

/* ===== Main ===== */
.main-content {
  background: var(--page-bg);
  min-height: 0;
  padding: 24px 28px;
}
.page-wrapper {
  max-width: 1440px;
}

/* ===== Transitions ===== */
.text-fade-enter-active, .text-fade-leave-active { transition: opacity 0.2s ease; }
.text-fade-enter-from, .text-fade-leave-to { opacity: 0; }

.page-enter-active { transition: opacity 0.3s ease, transform 0.3s ease; }
.page-leave-active { transition: opacity 0.15s ease; }
.page-enter-from { opacity: 0; transform: translateY(10px); }
.page-leave-to { opacity: 0; }

/* User trigger */
.user-trigger {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  padding: 6px 12px;
  border-radius: 8px;
  transition: background 0.2s;
  font-size: 13px;
  color: var(--text-secondary);
}
.user-trigger:hover {
  background: #F5F2EE;
}
.header-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  object-fit: cover;
  border: 1px solid var(--border-color);
}

.user-trigger .arrow {
  font-size: 10px;
  margin-left: 2px;
}
</style>
