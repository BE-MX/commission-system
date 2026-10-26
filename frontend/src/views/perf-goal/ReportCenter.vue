<template>
  <div class="perf-goal-page">
    <div class="pg-push-grid">
      <ReportRuleCard :schedule="schedule" />
      <ReportTimeline :schedule="schedule" />
    </div>

    <DeliveryLedger ref="ledger" @preview="openPreview" />

    <el-drawer v-model="previewVisible" title="报告预览" size="640px">
      <div v-loading="previewLoading">
        <ReportPreviewCard v-if="preview" :report="preview" />
        <el-empty v-else-if="!previewLoading" description="报告内容加载失败" :image-size="96" />
        <div v-if="preview" style="margin-top:16px;display:flex;justify-content:flex-end;gap:10px">
          <el-button type="primary" :loading="resending" @click="resend">补发此报告</el-button>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { msgSuccessText } from '@/utils/feedback'
import { perfGoalApi } from '@/api/perfGoal'
import ReportRuleCard from './components/ReportRuleCard.vue'
import ReportTimeline from './components/ReportTimeline.vue'
import ReportPreviewCard from './components/ReportPreviewCard.vue'
import DeliveryLedger from './components/DeliveryLedger.vue'

const schedule = ref(null)
const ledger = ref(null)
const previewVisible = ref(false), previewLoading = ref(false), resending = ref(false)
const preview = ref(null)

async function loadSchedule() {
  try {
    schedule.value = await perfGoalApi.reportSchedule({ suppressToast: true })
  } catch {
    schedule.value = null
  }
}
async function openPreview(row) {
  previewVisible.value = true
  previewLoading.value = true
  preview.value = null
  try {
    preview.value = await perfGoalApi.report(row.id, { suppressToast: true })
  } catch { /* 空态由 drawer 内展示 */ } finally {
    previewLoading.value = false
  }
}
async function resend() {
  if (!preview.value?.id) return
  resending.value = true
  try {
    await perfGoalApi.resendReport(preview.value.id)
    msgSuccessText('已重新推送')
    ledger.value?.reload()
  } finally {
    resending.value = false
  }
}
onMounted(loadSchedule)
</script>

<style src="./perf-goal.css"></style>
