<template>
  <article class="task-card" :class="{ 'is-overdue': task.overdue_days > 0, 'is-urgent': urgent }">
    <header class="task-head">
      <StatusBadge :value="task.task_type" :dictionary="TASK_TYPE_STATUS" size="small" />
      <span class="task-due">{{ dueLabel }}</span>
      <StatusBadge v-if="urgent" value="紧急" :dictionary="SEVERITY_STATUS" size="small" />
    </header>
    <p class="task-title">{{ task.title }}</p>
    <p v-if="task.task_type === 'receipt'" class="task-sub">
      {{ (task.payload.shipments || []).map(s => s.shipment_no).join('、') }}
    </p>
    <footer class="task-actions">
      <GlassButton v-permission="'domestic_followup:write'" variant="primary" @click="$emit('record', task)">记跟进</GlassButton>
      <GlassButton v-if="task.task_type === 'receipt'" v-permission="'domestic_followup:write'"
                   :loading="busy" @click="onReceiptOk">已回访无问题</GlassButton>
      <el-dropdown v-permission="'domestic_followup:write'" trigger="click" @command="days => $emit('snooze', task, days)">
        <GlassButton variant="link" right-icon="ArrowDown">顺延</GlassButton>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item v-for="d in [1, 3, 7]" :key="d" :command="d">{{ d }} 天</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
      <GlassButton variant="link" @click="$emit('timeline', task)">时间线</GlassButton>
    </footer>
  </article>
</template>

<script setup>
import { computed, ref } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import { currentBeijingDate } from '@/utils/datetime'
import { taskDueLabel } from '../followupDraft'
import { SEVERITY_STATUS, TASK_TYPE_STATUS } from '../followupStatus'

// 「已回访无问题」用函数 prop 而非 emit：要 await 父组件的请求，按钮 loading 才能真正防连点
const props = defineProps({ task: { type: Object, required: true }, onReceiptOk: { type: Function, required: true } })
defineEmits(['record', 'snooze', 'timeline'])
const urgent = computed(() => props.task.payload?.severity === '紧急')
const dueLabel = computed(() => taskDueLabel(props.task, currentBeijingDate()))
const busy = ref(false)

async function onReceiptOk() {
  busy.value = true
  try { await props.onReceiptOk(props.task) } finally { busy.value = false }
}
</script>

<style scoped>
.task-card { display: flex; flex-direction: column; gap: 6px; padding: 12px 14px; border: 1px solid var(--border-color); border-radius: var(--card-radius); background: var(--card-bg); }
.task-card.is-overdue { border-left: 3px solid var(--color-warning-text); }
.task-card.is-urgent { border-left: 3px solid var(--color-danger); }
.task-head { display: flex; align-items: center; gap: 8px; }
.task-due { font-size: 12px; color: var(--text-secondary); }
.is-overdue .task-due { color: var(--color-warning-text); }
.task-title { margin: 0; font-weight: 600; }
.task-sub { margin: 0; font-size: 12px; color: var(--text-secondary); }
.task-actions { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
@media (max-width: 768px) { .task-actions :deep(button) { min-height: 44px; } }
</style>
