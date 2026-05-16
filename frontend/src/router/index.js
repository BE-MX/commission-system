import { createRouter, createWebHistory } from 'vue-router'
import { NAV_ENTRIES } from '@/config/navigation'

// NAV_ENTRIES 中每条记录映射成 vue-router 的 children 路由
// path 去掉前导 '/' 因为父路由是 '/'
const layoutRoutes = NAV_ENTRIES.map(entry => ({
  path: entry.path.replace(/^\//, ''),
  name: entry.name,
  component: entry.component,
  meta: {
    title: entry.title,
    permission: entry.permission,
    anyPermission: entry.anyPermission,
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
    return next(from.fullPath || '/dashboard')
  }
  if (to.meta.anyPermission && !auth.hasAnyPermission(to.meta.anyPermission)) {
    const { ElMessage } = await import('element-plus')
    ElMessage.error('权限不足')
    return next(from.fullPath || '/dashboard')
  }

  next()
})

export default router
