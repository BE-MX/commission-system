<template>
  <el-dialog v-model="feedbackVisible" title="问题反馈" width="520px">
    <el-input
      v-model="feedbackContent"
      type="textarea"
      :rows="5"
      maxlength="2000"
      show-word-limit
      placeholder="描述本批次提成数据中的问题"
    />
    <template #footer>
      <GlassButton variant="ghost" @click="feedbackVisible = false">取消</GlassButton>
      <GlassButton variant="primary" :loading="submitting" @click="submitFeedback">提交</GlassButton>
    </template>
  </el-dialog>

  <el-dialog v-model="confirmVisible" title="提交确认" width="520px">
    <el-alert
      type="warning"
      :closable="false"
      show-icon
      title="一旦提交确认后将不能修改，如确认无误，则在下方输入框中输入‘我已确认’后点击提交。"
    />
    <el-input v-model="confirmText" class="confirm-input" placeholder="请输入：我已确认" />
    <template #footer>
      <GlassButton variant="ghost" @click="confirmVisible = false">取消</GlassButton>
      <GlassButton variant="primary" :loading="submitting" @click="submitConfirm">提交</GlassButton>
    </template>
  </el-dialog>
</template>

<script setup>
// 「我的提成」确认流程对话框：问题反馈 + 输入「我已确认」提交确认。
// 列表页与明细页共用；确认成功后 emit('confirmed') 由父级刷新数据。
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { confirmMyCommissionBatch, submitMyCommissionFeedback } from '@/api/commission'

const props = defineProps({
  batchId: { type: [Number, String], required: true },
})
const emit = defineEmits(['confirmed'])

const submitting = ref(false)
const feedbackVisible = ref(false)
const feedbackContent = ref('')
const confirmVisible = ref(false)
const confirmText = ref('')

function openFeedback() {
  feedbackContent.value = ''
  feedbackVisible.value = true
}

function openConfirm() {
  confirmText.value = ''
  confirmVisible.value = true
}

async function submitFeedback() {
  if (!feedbackContent.value.trim()) {
    ElMessage.warning('请输入反馈内容')
    return
  }
  submitting.value = true
  try {
    await submitMyCommissionFeedback(props.batchId, { content: feedbackContent.value.trim() })
    ElMessage.success('反馈已提交')
    feedbackVisible.value = false
  } finally {
    submitting.value = false
  }
}

async function submitConfirm() {
  if (confirmText.value !== '我已确认') {
    ElMessage.warning('请输入“我已确认”后再提交')
    return
  }
  submitting.value = true
  try {
    await confirmMyCommissionBatch(props.batchId, { confirmation_text: confirmText.value })
    ElMessage.success('确认成功')
    confirmVisible.value = false
    emit('confirmed')
  } finally {
    submitting.value = false
  }
}

defineExpose({ openFeedback, openConfirm })
</script>

<style scoped>
.confirm-input {
  margin-top: 18px;
}
</style>
