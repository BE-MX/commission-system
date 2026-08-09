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
        :default-active="route.meta.activeMenu || route.path"
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
          <template v-for="item in group.items" :key="item.path">
            <!-- external 条目：原生 <a> 新标签页直开，不走 el-menu 的 router/active 机制 -->
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
      </el-menu>

      <div class="sidebar-bottom" v-show="!isCollapse">
        <div class="env-badge">DEVELOPMENT</div>
      </div>
    </el-aside>

    <el-container class="right-container">
      <el-header class="header">
        <div class="header-left">
          <button v-if="!isNarrow" class="collapse-toggle" @click="isCollapse = !isCollapse">
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
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { NAV_ENTRIES, MENU_GROUPS } from '@/config/navigation'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const mobileQuery = globalThis.matchMedia?.('(max-width: 640px)')
const isNarrow = ref(mobileQuery?.matches ?? false)
const desktopCollapse = ref(false)
const isCollapse = computed({
  get: () => isNarrow.value || desktopCollapse.value,
  set: value => {
    if (!isNarrow.value) desktopCollapse.value = value
  },
})

function onNarrowChange(event) {
  isNarrow.value = event.matches
}

onMounted(() => mobileQuery?.addEventListener('change', onNarrowChange))
onBeforeUnmount(() => mobileQuery?.removeEventListener('change', onNarrowChange))

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
        .map(e => ({ path: e.path, title: e.menu.title ?? e.title, icon: e.menu.icon, external: e.external === true }))
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

/* ===== Sidebar =====
   深灰磨砂玻璃（2026-07-25）：与暖金内容区互补的冷板岩灰，
   自带静态微光；菜单项是浮在其上的暗色磨砂，激活项金渐变胶囊呼应品牌 */
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

/* 侧栏静态微光（同 .lg-aurora 配方：大半径渐变自然衰减，禁动画/禁 filter blur） */
.aside::before {
  content: "";
  position: absolute;
  width: 280px;
  height: 280px;
  top: -90px;
  right: -110px;
  border-radius: 50%;
  background: radial-gradient(circle, var(--sidebar-glow-gold) 0%, rgba(245, 203, 92, 0) 68%);
  pointer-events: none;
}
.aside::after {
  content: "";
  position: absolute;
  width: 300px;
  height: 300px;
  bottom: -110px;
  left: -130px;
  border-radius: 50%;
  background: radial-gradient(circle, var(--sidebar-glow-slate) 0%, rgba(107, 140, 186, 0) 68%);
  pointer-events: none;
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
  z-index: 1;
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
  color: rgba(255, 255, 255, 0.4);
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
  color: rgba(255, 255, 255, 0.32);
  padding: 20px 20px 8px;
  text-transform: uppercase;
  position: relative;
  z-index: 1;
}

/* Menu */
.side-menu {
  border-right: none;
  background: transparent;
  flex: 1;
  overflow-y: auto;
  padding: 0 8px;
  position: relative;
  z-index: 1;
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
  color: rgba(255, 255, 255, 0.55);
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
  background-color: rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.92);
}

/* 激活项：金渐变胶囊（同 GlassButton primary），白色文字 + 暖金投影 */
:deep(.el-menu-item.is-active) {
  color: #fff;
  background: linear-gradient(135deg, var(--color-gold), var(--color-primary));
  box-shadow: 0 4px 14px rgba(212, 148, 28, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.35);
  font-weight: 600;
}
:deep(.el-menu-item.is-active .el-icon) {
  color: #fff;
}
/* 激活项 hover 保持胶囊，不回落成磨砂 */
:deep(.el-menu-item.is-active:hover) {
  background: linear-gradient(135deg, var(--color-gold), var(--color-primary-hover));
  color: #fff;
}
:deep(.el-sub-menu.is-active > .el-sub-menu__title) {
  color: var(--color-gold);
  font-weight: 600;
}
:deep(.el-sub-menu .el-menu-item) {
  padding-left: 52px !important;
  font-size: 13px;
}

/* external 条目是 <a>：借用 .el-menu-item 类拿全套菜单项样式，这里只补 anchor 默认样式的差异 */
:deep(a.external-item) {
  text-decoration: none;
}
:deep(.ext-mark) {
  font-size: 11px;
  opacity: 0.45;
  margin-left: 4px;
}

/* Sidebar bottom */
.sidebar-bottom {
  padding: 16px;
  border-top: 1px solid rgba(245, 203, 92, 0.1);
  flex-shrink: 0;
  position: relative;
  z-index: 1;
}
.env-badge {
  font-family: var(--font-display);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.1em;
  color: var(--color-gold);
  background: rgba(245, 203, 92, 0.12);
  padding: 4px 8px;
  border-radius: 4px;
  text-align: center;
}

/* ===== Header ===== */
.right-container {
  background: var(--page-bg);
  min-width: 0;
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  /* 与液态玻璃体系同源的磨砂白（顶栏是布局栏不叠内容，无需 backdrop-filter） */
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.88), rgba(255, 255, 255, 0.68));
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

@media (max-width: 640px) {
  .header { padding: 0 10px; }
  .header-left { gap: 8px; min-width: 0; }
  .header-badge { display: none; }
  .main-content { padding: 12px 10px; }
  .page-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .user-trigger { padding-inline: 6px; }
  .user-trigger span, .user-trigger .arrow { display: none; }
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

<!-- 折叠态弹出子菜单 teleport 到 body，scoped 够不到，用全局样式；与侧栏同色系深灰磨砂 -->
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
.el-menu--popup .el-menu-item {
  color: rgba(255, 255, 255, 0.55);
  border-radius: 8px;
}
.el-menu--popup .el-menu-item:hover {
  background-color: rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.92);
}
.el-menu--popup .el-menu-item.is-active {
  color: #fff;
  background: linear-gradient(135deg, var(--color-gold), var(--color-primary));
  box-shadow: 0 4px 14px rgba(212, 148, 28, 0.35);
}
.el-menu--popup a.el-menu-item {
  text-decoration: none;
}
.el-menu--popup .ext-mark {
  font-size: 11px;
  opacity: 0.45;
  margin-left: 4px;
}
</style>
