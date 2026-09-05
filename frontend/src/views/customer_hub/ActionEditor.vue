<template>
  <el-dialog v-model="visible" append-to-body title="处理客户待办" width="min(620px, calc(100vw - 24px))" :close-on-click-modal="!workflowLoading" :close-on-press-escape="!workflowLoading" :show-close="!workflowLoading">
    <p>{{ current?.customer_name }} · {{ current?.next_action || actionLabels[current?.action_type] || current?.action_type }}</p>
    <el-alert v-if="workflowError" type="error" title="保存失败，请检查时间、权限或刷新待办状态后重试。已填写的内容仍保留。" :closable="false" show-icon />
    <el-form label-position="top" :disabled="workflowLoading" class="action-form">
      <el-form-item label="操作"><el-radio-group v-model="operation"><el-radio-button v-for="item in operationOptions" :key="item" :value="item">{{ operationLabels[item] }}</el-radio-button></el-radio-group></el-form-item>
      <template v-if="operation === 'complete'">
        <el-form-item label="沟通结果"><el-select v-model="form.outcomeCode"><el-option v-for="(label, value) in outcomeLabels" :key="value" :label="label" :value="value" /></el-select></el-form-item>
        <el-form-item label="实际渠道"><el-select v-model="form.channel"><el-option v-for="(label, value) in channelLabels" :key="value" :label="label" :value="value" /></el-select></el-form-item>
        <el-form-item label="发生时间（北京时间，留空为现在）"><el-date-picker v-model="form.occurredAt" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" /></el-form-item>
        <el-form-item label="结果摘要"><el-input v-model="form.summary" type="textarea" :rows="3" placeholder="客户反馈、当前需求或未接通情况" /></el-form-item>
        <el-form-item><el-checkbox v-model="form.scheduleNext">安排下一次跟进</el-checkbox></el-form-item>
        <el-form-item :label="form.scheduleNext ? '后续具体动作（必填）' : '下一步备注（可选）'"><el-input v-model="form.nextStep" placeholder="例如：发送样品清单并确认收货地址" /></el-form-item>
        <template v-if="form.scheduleNext">
          <el-form-item label="下次跟进时间（北京时间，必填）"><el-date-picker v-model="form.nextStepDueAt" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" /></el-form-item>
          <el-form-item label="后续动作"><el-select v-model="form.followupActionType"><el-option v-for="(label, value) in actionLabels" :key="value" :label="label" :value="value" /></el-select></el-form-item>
          <el-form-item label="后续渠道"><el-select v-model="form.followupChannel"><el-option v-for="(label, value) in channelLabels" :key="value" :label="label" :value="value" /></el-select></el-form-item>
          <p class="hint">下次待办负责人：{{ current?.owner_name || '原负责人' }}，沿用当前待办归属。</p>
        </template>
      </template>
      <el-form-item v-if="operation === 'snooze'" label="延后至（北京时间，必填）"><el-date-picker v-model="form.snoozedUntil" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" /></el-form-item>
      <el-form-item v-if="operation === 'dismiss'" label="忽略原因"><el-select v-model="form.reasonCode"><el-option v-for="value in dismissReasons" :key="value" :value="value" :label="reasonLabels[value]" /></el-select></el-form-item>
      <el-form-item v-if="['complete', 'feedback'].includes(operation)" label="建议是否有帮助"><el-radio-group v-model="form.feedback"><el-radio value="useful">有帮助</el-radio><el-radio value="not_useful">没有帮助</el-radio></el-radio-group></el-form-item>
      <el-form-item v-if="operation !== 'snooze'" label="建议反馈备注"><el-input v-model="form.note" /></el-form-item>
    </el-form>
    <template #footer><GlassButton variant="ghost" :disabled="workflowLoading" @click="visible = false">取消</GlassButton><GlassButton v-any-permission="['customer_radar:write','customer:admin']" variant="primary" :loading="workflowLoading" :disabled="!canSubmit || workflowLoading" @click="save">保存</GlassButton></template>
  </el-dialog>
</template>
<script setup>
import { computed, reactive, ref } from 'vue'
import { msgSuccess } from '@/utils/feedback'
import { parseApiDateTime } from '@/utils/datetime'
import { useRadarWorkflow } from './composables/useCustomerHub'
import { buildActionUpdate, getRadarOperationOptions } from './customerHubController'
import { actionLabels, channelLabels, operationLabels, outcomeLabels, reasonLabels } from './operationsPresentation'
const emit = defineEmits(['saved'])
const { workflowLoading, workflowError, submit } = useRadarWorkflow()
const visible = ref(false), current = ref(null), operation = ref('complete')
const defaults = () => ({ outcomeCode: 'contacted', channel: 'email', occurredAt: '', feedback: 'useful', summary: '', nextStep: '', scheduleNext: false, nextStepDueAt: '', followupActionType: 'email', followupChannel: 'email', snoozedUntil: '', reasonCode: 'user_dismissed', note: '' })
const form = reactive(defaults())
const dismissReasons = ['user_dismissed', 'duplicate', 'no_longer_relevant', 'wrong_customer', 'completed_elsewhere', 'policy_suppressed', 'other']
const operationOptions = computed(() => getRadarOperationOptions(current.value?.effective_status || current.value?.status))
const future = value => (parseApiDateTime(value)?.getTime() || 0) > Date.now()
const canSubmit = computed(() => operationOptions.value.includes(operation.value)
  && (operation.value !== 'snooze' || future(form.snoozedUntil))
  && (operation.value !== 'complete' || !form.scheduleNext || Boolean(form.nextStep.trim() && future(form.nextStepDueAt)))
  && (operation.value !== 'feedback' || Boolean(form.feedback)))
function open(row) {
  if (workflowLoading.value) return
  current.value = row; Object.assign(form, defaults(), { channel: row.channel || 'internal' })
  workflowError.value = null; operation.value = operationOptions.value[0] || ''; visible.value = true
}
async function save() {
  if (!canSubmit.value || workflowLoading.value) return
  if (await submit(current.value.action_id, buildActionUpdate(operation.value, form))) {
    visible.value = false; emit('saved'); msgSuccess(form.scheduleNext && operation.value === 'complete' ? '结果已登记，下次跟进已加入待办' : '待办已更新')
  }
}
defineExpose({ open })
</script>
<style scoped>.action-form :deep(.el-select), .action-form :deep(.el-date-editor) { width: 100%; }.hint { color: var(--text-secondary); font-size: 13px; }</style>
