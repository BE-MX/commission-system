import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/auth/LoginPage.vue'),
    meta: { title: '登录', public: true }
  },
  {
    path: '/',
    component: () => import('../views/layout/MainLayout.vue'),
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('../views/dashboard/Dashboard.vue'),
        meta: { title: '工作台' }
      },
      {
        path: 'employee/attribute',
        name: 'EmployeeAttribute',
        component: () => import('../views/employee/EmployeeAttribute.vue'),
        meta: { title: '员工属性管理' }
      },
      {
        path: 'supervisor/relation',
        name: 'SupervisorRelation',
        component: () => import('../views/supervisor/SupervisorRelation.vue'),
        meta: { title: '主管关系管理' }
      },
      {
        path: 'customer/snapshot',
        name: 'CustomerSnapshot',
        component: () => import('../views/customer/CustomerSnapshot.vue'),
        meta: { title: '客户归属管理' }
      },
      {
        path: 'payment/sync',
        name: 'PaymentSync',
        component: () => import('../views/payment/PaymentSync.vue'),
        meta: { title: '回款同步' }
      },
      {
        path: 'commission/batch',
        name: 'CommissionBatch',
        component: () => import('../views/commission/CommissionBatch.vue'),
        meta: { title: '提成批次' }
      },
      {
        path: 'commission/batch/:batchId/details',
        name: 'CommissionDetail',
        component: () => import('../views/commission/CommissionDetail.vue'),
        meta: { title: '提成明细' }
      },
      {
        path: 'tracking',
        name: 'TrackingList',
        component: () => import('../views/tracking/TrackingList.vue'),
        meta: { title: '物流跟踪' }
      },
      {
        path: 'tracking/:waybillNo',
        name: 'TrackingDetail',
        component: () => import('../views/tracking/TrackingDetail.vue'),
        meta: { title: '运单详情' }
      },
      {
        path: 'design/gantt',
        name: 'DesignGantt',
        component: () => import('../views/design/GanttView.vue'),
        meta: { title: '排期甘特图' }
      },
      {
        path: 'design/submit',
        name: 'DesignSubmit',
        component: () => import('../views/design/SubmitRequest.vue'),
        meta: { title: '提交预约' }
      },
      {
        path: 'design/my-requests',
        name: 'MyRequests',
        component: () => import('../views/design/MyRequests.vue'),
        meta: { title: '我的预约' }
      },
      {
        path: 'design/audit',
        name: 'DesignAudit',
        component: () => import('../views/design/AuditQueue.vue'),
        meta: { title: '审批队列' }
      },
      {
        path: 'design/manage',
        name: 'DesignManage',
        component: () => import('../views/design/DesignManage.vue'),
        meta: { title: '设计管理' }
      },
      {
        path: 'design/stats',
        name: 'DesignStats',
        component: () => import('../views/design/DesignStats.vue'),
        meta: { title: '设计统计' }
      },
      {
        path: 'system/users',
        name: 'UserManagement',
        component: () => import('../views/system/UserManagement.vue'),
        meta: { title: '用户管理', permission: 'user:read' }
      },
      {
        path: 'system/roles',
        name: 'RoleManagement',
        component: () => import('../views/system/RoleManagement.vue'),
        meta: { title: '角色权限管理', permission: 'user:read' }
      },
      {
        path: 'system/dicts',
        name: 'DictManagement',
        component: () => import('../views/system/DictManagement.vue'),
        meta: { title: '基础字典', permission: 'user:read' }
      },
      {
        path: 'profile',
        name: 'Profile',
        component: () => import('../views/profile/ProfilePage.vue'),
        meta: { title: '个人设置' }
      }
    ]
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// ── 路由守卫 ──────────────────────────────────────────
router.beforeEach(async (to, from, next) => {
  // 设置页面标题
  document.title = to.meta.title ? `${to.meta.title} - 莱莎方舟` : '莱莎方舟'

  // 公开页面直接放行
  if (to.meta.public) return next()

  // 动态引入 store（避免在 router 初始化时 pinia 未就绪）
  const { useAuthStore } = await import('@/stores/auth')
  const auth = useAuthStore()

  // 未登录：跳转登录页
  if (!auth.isLoggedIn) {
    return next({ name: 'Login', query: { redirect: to.fullPath } })
  }

  // 权限检查
  if (to.meta.permission && !auth.hasPermission(to.meta.permission)) {
    const { ElMessage } = await import('element-plus')
    ElMessage.error('权限不足')
    return next(from.fullPath || '/dashboard')
  }

  next()
})

export default router
