<template>
  <div v-if="data.showTodoArea" class="dashboard-todos">
    <!-- 审批待办 -->
    <div
      v-if="authStore.hasAnyPermission(['design:audit']) && data.pendingApprovals > 0"
      class="todo-alert todo-alert-warning"
      @click="$router.push('/design/audit')"
    >
      <div class="todo-alert-left">
        <el-icon class="todo-icon"><Bell /></el-icon>
        <span class="todo-text">您有 {{ data.pendingApprovals }} 条预约待审批</span>
      </div>
      <span class="todo-link">前往处理 <el-icon class="todo-arrow"><ArrowRight /></el-icon></span>
    </div>

    <!-- 今日拍摄提醒 -->
    <div
      v-if="authStore.hasAnyPermission(['design:manage']) && data.todayShootCount > 0"
      class="todo-alert todo-alert-warning"
      @click="$router.push('/design/gantt')"
    >
      <div class="todo-alert-left">
        <el-icon class="todo-icon"><Bell /></el-icon>
        <span class="todo-text">今日有 {{ data.todayShootCount }} 项拍摄安排</span>
      </div>
      <span class="todo-link">前往处理 <el-icon class="todo-arrow"><ArrowRight /></el-icon></span>
    </div>

    <!-- 归属待补充 -->
    <div
      v-if="authStore.hasAnyPermission(['customer:write']) && data.incompleteCount > 0"
      class="todo-alert todo-alert-primary"
      @click="$router.push('/customer/snapshot')"
    >
      <div class="todo-alert-left">
        <el-icon class="todo-icon"><Warning /></el-icon>
        <span class="todo-text">有 {{ data.incompleteCount }} 条客户归属信息待补充</span>
      </div>
      <span class="todo-link">前往处理 <el-icon class="todo-arrow"><ArrowRight /></el-icon></span>
    </div>

    <!-- 物流异常 -->
    <div
      v-if="authStore.hasAnyPermission(['tracking:read']) && data.trackingAbnormal > 0"
      class="todo-alert todo-alert-danger"
      @click="$router.push('/tracking')"
    >
      <div class="todo-alert-left">
        <el-icon class="todo-icon"><WarningFilled /></el-icon>
        <span class="todo-text">检测到 {{ data.trackingAbnormal }} 单物流异常</span>
      </div>
      <span class="todo-link">前往处理 <el-icon class="todo-arrow"><ArrowRight /></el-icon></span>
    </div>
  </div>
</template>

<script setup>
import { useAuthStore } from '@/stores/auth'
import { ArrowRight, Bell, Warning, WarningFilled } from '@element-plus/icons-vue'

defineProps({
  data: { type: Object, required: true },
})

const authStore = useAuthStore()
</script>

<style scoped>
.dashboard-todos {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* 色调玻璃变体：色底半透明 + blur，紧急信息浮在光斑之上 */
.todo-alert {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 18px;
  border-radius: 14px;
  cursor: pointer;
  -webkit-backdrop-filter: blur(var(--dash-glass-blur));
  backdrop-filter: blur(var(--dash-glass-blur));
  border: 1px solid var(--dash-glass-border);
  box-shadow: var(--dash-glass-highlight);
  transition: transform 200ms var(--ease-out-strong), box-shadow 200ms var(--ease-out-strong);
}
.todo-alert:active {
  transform: scale(0.99);
}
@media (hover: hover) and (pointer: fine) {
  .todo-alert:hover {
    transform: translateY(-1px);
    box-shadow: var(--dash-glass-highlight), var(--dash-glass-shadow-hover);
  }
}
@media (prefers-reduced-motion: reduce) {
  .todo-alert:hover, .todo-alert:active {
    transform: none;
  }
}

.todo-alert-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.todo-text {
  font-family: var(--font-body);
  font-size: 14px;
  font-weight: 500;
}

.todo-link {
  font-family: var(--font-display);
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.todo-alert-warning {
  background: rgba(245, 203, 92, 0.22);
  color: var(--color-warning-text);
}
.todo-alert-warning .todo-link {
  color: var(--color-primary);
}

.todo-alert-primary {
  background: rgba(212, 148, 28, 0.14);
  color: var(--color-primary);
}
.todo-alert-primary .todo-link {
  color: var(--color-primary);
}

.todo-alert-danger {
  background: rgba(192, 57, 43, 0.12);
  color: var(--color-danger);
}
.todo-alert-danger .todo-link {
  color: var(--color-danger);
}

@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
  .todo-alert-warning { background: var(--color-warning-bg); }
  .todo-alert-primary { background: var(--color-primary-light); }
  .todo-alert-danger  { background: var(--color-danger-bg); }
}

@media (max-width: 479px) {
  .todo-alert {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
}
</style>
