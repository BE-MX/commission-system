<template>
  <div class="workflow">
    <el-alert v-if="workflowError" type="error" title="经营动作更新失败，当前状态未改变，请检查字段或权限后重试。" :closable="false" show-icon />
    <CustomerHubWorkspace :key="refreshKey" kind="radar" @operate-action="open" />
    <el-dialog v-model="visible" title="处理经营动作" width="620">
      <el-form label-position="top" class="radar-form">
        <el-form-item label="操作"><el-radio-group v-model="operation"><el-radio-button v-for="item in operationOptions" :key="item" :value="item">{{ operationLabel(item) }}</el-radio-button></el-radio-group></el-form-item>
        <template v-if="operation === 'complete'">
          <el-form-item label="结果"><el-select v-model="form.outcomeCode"><el-option v-for="item in outcomeOptions" :key="item" :label="item" :value="item" /></el-select></el-form-item>
          <el-form-item label="渠道"><el-select v-model="form.channel" clearable><el-option v-for="item in channelOptions" :key="item" :label="item" :value="item" /></el-select></el-form-item>
          <el-form-item label="发生时间（北京时间，可选）"><el-date-picker v-model="form.occurredAt" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" /></el-form-item>
          <el-form-item label="摘要"><el-input v-model="form.summary" type="textarea" /></el-form-item><el-form-item label="下一步"><el-input v-model="form.nextStep" /></el-form-item>
          <el-form-item label="建议质量反馈"><el-radio-group v-model="form.feedback"><el-radio value="useful">有效</el-radio><el-radio value="not_useful">无效</el-radio></el-radio-group></el-form-item><el-form-item label="反馈备注"><el-input v-model="form.note" /></el-form-item>
        </template>
        <template v-else-if="operation === 'feedback'"><el-form-item label="建议质量反馈（必填）"><el-radio-group v-model="form.feedback"><el-radio value="useful">有效</el-radio><el-radio value="not_useful">无效</el-radio></el-radio-group></el-form-item><el-form-item label="反馈备注"><el-input v-model="form.note" type="textarea" /></el-form-item></template>
        <el-form-item v-else-if="operation === 'snooze'" label="延后至（北京时间）"><el-date-picker v-model="form.snoozedUntil" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" /></el-form-item>
        <template v-else-if="operation === 'dismiss'"><el-form-item label="忽略原因"><el-select v-model="form.reasonCode"><el-option v-for="item in dismissReasonOptions" :key="item" :label="item" :value="item" /></el-select></el-form-item><el-form-item label="备注"><el-input v-model="form.note" type="textarea" /></el-form-item></template>
      </el-form>
      <template #footer><el-button @click="visible = false">取消</el-button><el-button v-any-permission="['customer_radar:write','customer:admin']" type="primary" :loading="workflowLoading" :disabled="!canSubmit" @click="save">确认</el-button></template>
    </el-dialog>
  </div>
</template>
<script setup>
import { computed, reactive, ref } from 'vue'
import { msgSuccess } from '@/utils/feedback'
import CustomerHubWorkspace from './CustomerHubWorkspace.vue'
import { useRadarWorkflow } from './composables/useCustomerHub'
import { buildActionUpdate, getRadarOperationOptions } from './customerHubController'
const { workflowLoading, workflowError, submit } = useRadarWorkflow()
const visible = ref(false), currentId = ref(null), refreshKey = ref(0), operation = ref('complete'), operationOptions = ref([])
const outcomeOptions = ['contacted', 'replied', 'no_response', 'meeting_booked', 'wrong_contact', 'other']
const channelOptions = ['alibaba', 'email', 'whatsapp', 'phone', 'linkedin', 'offline', 'internal']
const dismissReasonOptions = ['user_dismissed', 'duplicate', 'no_longer_relevant', 'wrong_customer', 'completed_elsewhere', 'policy_suppressed', 'other']
const form = reactive({ outcomeCode: 'contacted', channel: '', occurredAt: '', feedback: 'useful', summary: '', nextStep: '', snoozedUntil: '', reasonCode: 'user_dismissed', note: '' })
const canSubmit = computed(() => operationOptions.value.includes(operation.value)
  && (operation.value !== 'snooze' || Boolean(form.snoozedUntil))
  && (operation.value !== 'feedback' || Boolean(form.feedback)))
const operationLabel = item => ({ complete: '完成', snooze: '延后', dismiss: '忽略', feedback: '仅反馈' }[item] || item)
function open(row) { currentId.value = row.action_id; operationOptions.value = getRadarOperationOptions(row.status); operation.value = operationOptions.value[0] || ''; Object.assign(form, { outcomeCode: 'contacted', channel: '', occurredAt: '', feedback: 'useful', summary: '', nextStep: '', snoozedUntil: '', reasonCode: 'user_dismissed', note: '' }); visible.value = true }
async function run(payload, message) { if (await submit(currentId.value, payload)) { visible.value = false; refreshKey.value++; msgSuccess(message) } }
const save = () => run(buildActionUpdate(operation.value, form), ({ complete: '经营动作已完成', snooze: '经营动作已延后', dismiss: '经营动作已忽略', feedback: '经营建议反馈已提交' })[operation.value])
</script>
<style scoped>.workflow { display: grid; gap: 12px; }.radar-form :deep(.el-select),.radar-form :deep(.el-date-editor) { width: 100%; }</style>
