import { createRouter, createWebHistory } from 'vue-router'
import { NAV_ENTRIES } from '@/config/navigation'
import { recordRecentNav } from '@/utils/recentNav'
import {
  bypassCustomerImageRoute,
  captureCustomerImageRouteToken,
} from './customerImageRoute'
import {
  EXPO_KIOSK_PATH,
  expoKioskLoginLocation,
  guardExpoKioskBoundary,
  isExpoKioskTarget,
} from './expoKioskRoute'
import { readSessionItem } from '@/utils/safeSessionStorage'

// NAV_ENTRIES 中每条记录映射成 vue-router 的 children 路由
// path 去掉前导 '/' 因为父路由是 '/'
// external 条目（静态页/外链）只进菜单不进路由
const layoutRoutes = NAV_ENTRIES.filter(entry => !entry.external).map(entry => ({
  path: entry.path.replace(/^\//, ''),
  name: entry.name,
  component: entry.component,
  meta: {
    title: entry.title,
    permission: entry.permission,
    anyPermission: entry.anyPermission,
    activeMenu: entry.activeMenu,
  },
}))

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/auth/LoginPage.vue'),
    meta: { title: '登录', public: true },
  },
  {
    // 展会试戴 kiosk — 独立于 MainLayout 的全屏页（展位 iPad 全天运行）
    path: '/expo/kiosk',
    name: 'ExpoKiosk',
    component: () => import('@/views/expo/ExpoKiosk.vue'),
    meta: { title: 'AI 智能试戴', permission: 'expo:write' },
  },
  {
    // 对外库存查询 — 客户公开页（无登录无 key，全公开；数据层只出四要素 + 有货标识）
    path: '/inventory',
    name: 'PublicInventory',
    component: () => import('@/views/stock/PublicInventory.vue'),
    meta: { title: 'Stock Availability', public: true },
  },
  {
    path: '/create/:token?',
    name: 'CustomerImagePortal',
    component: () => import('@/views/customer-image/CustomerImagePortal.vue'),
    meta: { title: '莱莎产品效果图', public: true, customerImage: true },
    beforeEnter(to) {
      return captureCustomerImageRouteToken(to.params.token)
    },
  },
  {
    path: '/',
    component: () => import('@/views/layout/MainLayout.vue'),
    redirect: '/dashboard',
    children: layoutRoutes,
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// ── 路由守卫 ──────────────────────────────────────────
router.beforeEach(async (to, from, next) => {
  // 展会设备标签页与方舟后台硬隔离：先于所有公开页/移动端分流执行，
  // 因此浏览器后退、内部误跳、401 后重新登录都不能落进 MainLayout。
  const kioskBoundary = guardExpoKioskBoundary(to)
  if (kioskBoundary) return next(kioskBoundary)

  if (bypassCustomerImageRoute(to, next, title => { document.title = title })) return

  const isMobileUA = /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent)
  const desktopMode = readSessionItem('ark_desktop_mode') === '1'

  // 移动端访问登录页：直接走移动端独立登录页
  // 例外：目标是展会 kiosk（展位 iPad 用主站登录，不进移动端素材页）
  const redirectTarget = String(to.query.redirect || '')
  if (isMobileUA && !desktopMode && to.path === '/login' && !redirectTarget.startsWith('/expo')) {
    window.location.href = '/m/login.html'
    return false
  }

  // 移动端访问素材管理相关页面时，直接跳转到移动端独立页面
  if (isMobileUA && !desktopMode && to.path.startsWith('/asset/')) {
    window.location.href = '/m/'
    return false
  }

  // 设置页面标题
  document.title = to.meta.title ? `${to.meta.title} - 莱莎方舟` : '莱莎方舟'

  // 公开页面直接放行
  if (to.meta.public) return next()

  // 动态引入 store(避免在 router 初始化时 pinia 未就绪)
  const { useAuthStore } = await import('@/stores/auth')
  const auth = useAuthStore()

  // 等待 App.vue 初始化(刷新时 refresh_token 换取 access_token)完成
  await auth.initPromise

  // 未登录:跳转登录页
  if (!auth.isLoggedIn) {
    return next({ name: 'Login', query: { redirect: to.fullPath } })
  }

  // 权限检查 — 支持 permission(单权限) 与 anyPermission(任一即可)
  if (to.meta.permission && !auth.hasPermission(to.meta.permission)) {
    const { ElMessage } = await import('element-plus')
    ElMessage.error('权限不足')
    // 首次打开 kiosk 时 from.fullPath 是 '/'；沿用通用兜底会把展会设备送进后台。
    // kiosk 只允许回专用登录页，重新认证后仍固定回 kiosk。
    if (isExpoKioskTarget(to)) {
      return next(expoKioskLoginLocation({ reason: 'permission' }))
    }
    return next(from.fullPath || '/dashboard')
  }
  if (to.meta.anyPermission && !auth.hasAnyPermission(to.meta.anyPermission)) {
    const { ElMessage } = await import('element-plus')
    ElMessage.error('权限不足')
    return next(from.fullPath || '/dashboard')
  }

  next()
})

// ── 最近使用记录（工作台「最近使用」快跳的数据源）──────────────
// 只记侧边栏菜单页（entry.menu 存在），工作台本身与详情页不进列表；
// 被中止的导航（移动端重定向/权限拦截）不算到访
const MENU_ENTRY_BY_NAME = new Map(
  NAV_ENTRIES.filter(entry => entry.menu).map(entry => [entry.name, entry])
)
router.afterEach((to, from, failure) => {
  if (failure) return
  const entry = MENU_ENTRY_BY_NAME.get(to.name)
  if (!entry || entry.name === 'Dashboard') return
  recordRecentNav({ name: entry.name, path: to.fullPath })
})

export default router
