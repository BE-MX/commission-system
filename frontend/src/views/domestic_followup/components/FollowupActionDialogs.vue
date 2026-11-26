<template>
  <el-dialog v-model="visible" :title="titles[mode]" width="480px" append-to-body
             :show-close="!saving" :close-on-click-modal="!saving" :close-on-press-escape="!saving">
    <el-form label-position="top" @submit.prevent>
      <p v-if="mode === 'delete'" class="delete-target">确定从待办列表中删除「{{ task.title }}」？</p>
      <p v-else-if="task?.payload?.done_criteria" class="criteria">完成标准：{{ task.payload.done_criteria }}</p>
      <el-form-item v-if="mode === 'reschedule'" label="新的到期日" required>
        <el-date-picker v-model="dueDate" type="date" value-format="YYYY-MM-DD" class="full" />
      </el-form-item>
      <el-form-item v-else-if="needsNote" :label="mode === 'complete' ? '做了什么' : '删除理由'" required>
        <el-input v-model="note" type="textarea" :rows="3" maxlength="500" show-word-limit
                  :placeholder="mode === 'complete' ? '例如：方案已微信发给客户，并告知反馈时间' : '例如：客户改为到店自取'" />
      </el-form-item>
    </el-form>
    <template #footer>
      <GlassButton :disabled="saving" @click="visible = false">{{ mode === 'delete' ? '取消' : '返回' }}</GlassButton>
      <GlassButton :variant="mode === 'delete' ? 'danger' : 'primary'" :loading="saving"
                   :disabled="mode === 'reschedule' ? !dueDate : needsNote && !note.trim()" @click="submit">
        {{ mode === 'delete' ? '确认删除' : '确认' }}
      </GlassButton>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import { apiError, followupApi } from '@/api/domesticFollowup'
import { msgError, msgSuccessText } from '@/utils/feedback'

const emit = defineEmits(['saved'])
const visible = ref(false), saving = ref(false), mode = ref('complete'), task = ref(null), note = ref(''), dueDate = ref(null)
const titles = { complete: '完成行动待办', reschedule: '修改行动日期', delete: '删除待办' }
const needsNote = computed(() => mode.value === 'complete' || (mode.value === 'delete' && task.value?.task_type === 'action'))
function open(nextMode, row) {
  mode.value = nextMode
  task.value = row
  note.value = ''
  dueDate.value = row.due_date
  visible.value = true
}
async function submit() {
  saving.value = true
  try {
    if (mode.value === 'complete') await followupApi.completeAction(task.value.id, { note: note.value.trim() })
    else if (mode.value === 'reschedule') await followupApi.updateAction(task.value.id, { due_date: dueDate.value })
    else if (task.value.task_type === 'action') await followupApi.cancelAction(task.value.id, { reason: note.value.trim() })
    else await followupApi.deleteTask(task.value.id)
    visible.value = false
    msgSuccessText({ complete: '行动待办已完成', reschedule: '到期日已修改', delete: '待办已删除' }[mode.value])
    emit('saved', task.value)
  } catch (e) { msgError(apiError(e, '操作失败'), e) }
  finally { saving.value = false }
}
defineExpose({ open })
</script>

<style scoped>
.full { width: 100%; }
.delete-target { margin: 0 0 12px; overflow-wrap: anywhere; }
.criteria { margin: 0 0 12px; padding: 10px 12px; border-radius: var(--radius-sm); color: var(--text-secondary); background: var(--tag-neutral-bg); }
</style>
