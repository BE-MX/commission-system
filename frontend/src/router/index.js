import { createRouter, createWebHistory } from 'vue-router'

const routes = [
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
      }
    ]
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
