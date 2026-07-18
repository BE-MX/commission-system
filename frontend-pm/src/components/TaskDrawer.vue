<template>
  <UiDrawer :model-value="modelValue" :title="task ? '编辑任务' : '新建任务'" eyebrow="TASK" @update:model-value="onToggle">
    <form class="task-form" @submit.prevent="submit">
      <div class="form-item">
        <label class="field-label">标题 *</label>
        <input v-model.trim="form.title" class="input" type="text" placeholder="一句话说清楚要做什么" required />
      </div>
      <div class="form-item">
        <label class="field-label">描述</label>
        <textarea v-model.trim="form.description" class="textarea" placeholder="背景、验收标准、相关资料…"></textarea>
      </div>
      <div class="form-row">
        <div class="form-item">
          <label class="field-label">负责人</label>
          <select v-model="form.assignee" class="select">
            <option value="">未指派</option>
            <option v-for="m in members" :key="m.username" :value="m.username">{{ m.display_name }}</option>
          </select>
        </div>
        <div class="form-item">
          <label class="field-label">截止日期</label>
          <input v-model="form.due_date" class="input" type="date" />
        </div>
      </div>
      <div class="form-row">
        <div class="form-item">
          <label class="field-label">所属 Phase</label>
          <select v-model="form.phase" class="select">
            <option :value="null">不归属</option>
            <option v-for="p in [1, 2, 3, 4]" :key="p" :value="p">Phase {{ p }}</option>
          </select>
        </div>
        <div class="form-item" v-if="task">
          <label class="field-label">状态</label>
          <select v-model="form.status" class="select">
            <option v-for="(meta, s) in TASK_STATUS" :key="s" :value="s">{{ meta.label }}</option>
          </select>
        </div>
      </div>
      <div class="form-item" v-if="form.status === 'blocked'">
        <label class="field-label">受阻原因 *</label>
        <input v-model.trim="form.blocked_reason" class="input" type="text" placeholder="如：等顾问给 OKKI 接口权限" />
      </div>
      <div class="form-item">
        <label class="field-label">关联资料（可多选）</label>
        <div class="mat-picker">
          <label v-for="m in materialOptions" :key="m.id" class="mat-option" :class="{ checked: form.material_ids.includes(m.id) }">
            <input type="checkbox" :value="m.id" v-model="form.material_ids" />
            <span class="mat-option-name">{{ m.list_no ? `#${m.list_no} ` : '' }}{{ m.name }}</span>
            <StatusBadge :label="MATERIAL_STATUS[m.status]?.label || m.status" :tone="MATERIAL_STATUS[m.status]?.tone" />
          </label>
          <p v-if="!materialOptions.length" class="mat-empty">资料库还是空的</p>
        </div>
      </div>
    </form>
    <template #footer>
      <button class="btn" type="button" :disabled="busy" @click="onToggle(false)">取消</button>
      <button class="btn btn-primary" type="button" :disabled="busy || !form.title" @click="submit">
        <span v-if="busy" class="spinner"></span>{{ task ? '保存' : '创建' }}
      </button>
    </template>
  </UiDrawer>
</template>

<script setup>
import { reactive, ref, watch } from 'vue'
import StatusBadge from './StatusBadge.vue'
import UiDrawer from './UiDrawer.vue'
import { MATERIAL_STATUS, TASK_STATUS } from '../utils/labels.js'

const props = defineProps({
  modelValue: Boolean,
  task: { type: Object, default: null }, // null = 新建
  members: { type: Array, default: () => [] },
  materialOptions: { type: Array, default: () => [] },
  // @save 以函数 prop 承接：emit() 拿不到监听器返回的 Promise，无法等保存完成再关抽屉
  onSave: Function,
})
const emit = defineEmits(['update:modelValue'])

const busy = ref(false)
const form = reactive({
  title: '',
  description: '',
  assignee: '',
  due_date: '',
  phase: null,
  status: 'todo',
  blocked_reason: '',
  material_ids: [],
})

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    const t = props.task
    form.title = t?.title || ''
    form.description = t?.description || ''
    form.assignee = t?.assignee || ''
    form.due_date = t?.due_date || ''
    form.phase = t?.phase ?? null
    form.status = t?.status || 'todo'
    form.blocked_reason = t?.blocked_reason || ''
    form.material_ids = (t?.materials || []).map((m) => m.id)
  },
  { immediate: true }
)

function onToggle(open) {
  if (!open && busy.value) return // 保存中不许关抽屉，失败时表单要留在原地可重试
  emit('update:modelValue', open)
}

async function submit() {
  if (busy.value) return
  if (form.status === 'blocked' && !form.blocked_reason) return
  busy.value = true
  try {
    await props.onSave?.(props.task?.id || null, {
      title: form.title,
      description: form.description || null,
      assignee: form.assignee || null,
      due_date: form.due_date || null,
      phase: form.phase,
      ...(props.task ? { status: form.status, blocked_reason: form.blocked_reason || null } : {}),
      material_ids: form.material_ids,
    })
    emit('update:modelValue', false)
  } catch {
    // 失败留在抽屉内可改后重试；错误提示已由 api client 统一弹出
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.task-form { display: flex; flex-direction: column; gap: 18px; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.mat-picker {
  border: 1px solid var(--hairline);
  border-radius: var(--radius);
  max-height: 220px;
  overflow-y: auto;
}
.mat-option {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  font-size: 13px;
  cursor: pointer;
  border-bottom: 1px solid var(--hairline);
  transition: background var(--dur-fast) var(--ease-out);
}
.mat-option:last-child { border-bottom: none; }
.mat-option input { accent-color: var(--gold-strong); }
.mat-option.checked { background: var(--paper-sunken); }
.mat-option-name { flex: 1; }
.mat-empty { padding: 16px; text-align: center; color: var(--ink-4); font-size: 12.5px; }
</style>
