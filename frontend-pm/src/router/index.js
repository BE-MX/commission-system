import { createRouter, createWebHistory } from 'vue-router'
import { identity } from '../stores/identity.js'

const routes = [
  { path: '/', name: 'gate', component: () => import('../views/GateView.vue'), meta: { public: true } },
  {
    path: '/',
    component: () => import('../components/AppShell.vue'),
    children: [
      { path: 'dashboard', name: 'dashboard', component: () => import('../views/DashboardView.vue') },
      { path: 'tasks', name: 'tasks', component: () => import('../views/TasksView.vue') },
      { path: 'materials', name: 'materials', component: () => import('../views/MaterialsView.vue') },
      { path: 'materials/:id(\\d+)', name: 'material-detail', component: () => import('../views/MaterialDetailView.vue') },
      { path: 'activity', name: 'activity', component: () => import('../views/ActivityView.vue') },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
]

export const router = createRouter({
  // BASE_URL 随构建 base 走：云端根路径构建为 '/'，内网入口构建（deploy.bat --base=/pm/）为 '/pm/'
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

// 无 token 一律回门牌页；半登录态不存在——token 即全部（用户名校验在服务端逐请求回查）
router.beforeEach((to) => {
  if (to.meta.public) return true
  if (!identity.token) return { name: 'gate' }
  return true
})

router.afterEach((to) => {
  document.title = to.name === 'gate' ? '莱莎 AI 陪跑项目站' : `${to.meta.title || ''}莱莎 AI 陪跑项目站`
})
