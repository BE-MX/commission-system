<template>
  <div class="workspace-maintenance">
    <section class="lg-card panel">
      <h3>维护计划</h3>
      <div class="toolbar">
        <el-button type="primary" v-permission="'customer_pcw:write'" @click="dialogVisible = true">新建计划</el-button>
      </div>
      <el-empty v-if="!plans.length" description="暂无维护计划" :image-size="60" />
      <el-table class="list-table" v-else :data="plans" size="small" border>
        <el-table-column prop="plan_type" label="类型" min-width="90" />
        <el-table-column prop="title" label="标题" min-width="140" show-overflow-tooltip />
        <el-table-column prop="status" label="状态" min-width="90" />
        <el-table-column prop="plan_version" label="版本" min-width="70" />
        <el-table-column label="操作" min-width="110" class-name="table-action-column" fixed="right">
          <template #default="{ row }">
            <GlassButton variant="link" v-permission="'customer_pcw:write'" @click="pauseOrResume(row)">
              {{ row.status === 'active' ? '暂停' : '恢复' }}
            </GlassButton>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <section class="lg-card panel">
      <h3>样品事项 <span class="hint">签收不自动开始测试</span></h3>
      <el-empty v-if="!samples.length" description="暂无样品事项" :image-size="60" />
      <el-steps v-for="item in samples" :key="item.id" :active="stageIndex(item.stage)" size="small" class="sample-steps" align-center>
        <el-step v-for="stage in SAMPLE_STAGE_FLOW" :key="stage" :title="SAMPLE_STAGE_LABELS[stage]" />
      </el-steps>
      <el-table class="list-table" :data="samples" size="small" border>
        <el-table-column prop="stage" label="阶段" min-width="130" />
        <el-table-column prop="test_planned_date" label="计划测试" min-width="110" />
        <el-table-column prop="feedback_text" label="反馈" min-width="140" show-overflow-tooltip />
        <el-table-column label="操作" min-width="220" class-name="table-action-column" fixed="right">
          <template #default="{ row }">
            <GlassButton
              v-for="operation in sampleCaseOperations(row.stage)"
              :key="operation"
              variant="link"
              v-permission="'customer_pcw:write'"
              @click="patchSample(row, operation)"
            >{{ SAMPLE_OPERATION_LABELS[operation] }}</GlassButton>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <section class="lg-card panel">
      <h3>改约（实例日期，原期限保留）</h3>
      <el-form inline size="small" @submit.prevent>
        <el-form-item label="实例 ID">
          <el-input-number v-model="rescheduleForm.occurrenceId" :min="1" />
        </el-form-item>
        <el-form-item label="新日期">
          <el-date-picker v-model="rescheduleForm.date" type="date" value-format="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label="原因">
          <el-input v-model="rescheduleForm.reason" style="width: 180px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" v-permission="'customer_pcw:write'" @click="submitReschedule">改约</el-button>
        </el-form-item>
      </el-form>
    </section>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import {
  listMaintenancePlans, listSampleCases, patchMaintenancePlan,
  patchSampleCase, rescheduleOccurrence,
} from '@/api/customerHub'
import { msgSuccess } from '@/utils/feedback'
import {
  SAMPLE_OPERATION_LABELS, SAMPLE_STAGE_FLOW, SAMPLE_STAGE_LABELS,
  buildSampleCasePayload, sampleCaseOperations,
} from '../customerWorkspaceController'

const props = defineProps({ customerId: { type: Number, required: true }, customer: { type: Object, default: null } })
const plans = ref([])
const samples = ref([])
const dialogVisible = ref(false)
const rescheduleForm = reactive({ occurrenceId: 1, date: '', reason: '' })

const stageIndex = stage => Math.max(0, SAMPLE_STAGE_FLOW.indexOf(stage))

async function loadAll() {
  try {
    const [planRes, sampleRes] = await Promise.all([
      listMaintenancePlans(props.customerId, {}),
      listSampleCases(props.customerId, {}),
    ])
    plans.value = planRes.data?.items ?? []
    samples.value = sampleRes.data?.items ?? []
  } catch { /* 拦截器已提示 */ }
}

async function pauseOrResume(row) {
  try {
    await patchMaintenancePlan(row.id, {
      expected_plan_version: row.plan_version,
      status: row.status === 'active' ? 'paused' : 'active',
    }, `plan-${row.id}-${Date.now()}`)
    msgSuccess('计划状态已更新')
    await loadAll()
  } catch { /* 拦截器已提示 */ }
}

async function patchSample(row, operation) {
  try {
    const form = {
      test_planned_date: operation === 'reschedule'
        ? window.prompt('新计划测试日期 YYYY-MM-DD', row.test_planned_date || '')
        : undefined,
      reason: operation === 'reschedule' || operation === 'close'
        ? window.prompt('原因', '') : undefined,
      feedback: operation === 'record_feedback' ? window.prompt('客户反馈内容', '') : undefined,
      feedback_date: operation === 'record_feedback' ? new Date().toISOString().slice(0, 10) : undefined,
      actual_date: operation === 'start_test'
        ? new Date().toISOString().slice(0, 10) : undefined,
      evidence_message_ids: operation === 'start_test' ? [0] : undefined,
    }
    const payload = buildSampleCasePayload(operation, form, {
      expected_sample_version: row.sample_version,
      expected_occurrence_version: row.occurrence_version,
      expected_action_version: row.action_version,
    })
    await patchSampleCase(row.id, payload, `sample-${row.id}-${Date.now()}`)
    msgSuccess('样品事项已更新')
    await loadAll()
  } catch { /* 拦截器已提示（含阶段/版本错误码） */ }
}

async function submitReschedule() {
  try {
    await rescheduleOccurrence(rescheduleForm.occurrenceId, {
      occurrence_id: rescheduleForm.occurrenceId,
      occurrence_date: rescheduleForm.date,
      reason: rescheduleForm.reason,
    }, `reschedule-${rescheduleForm.occurrenceId}-${Date.now()}`)
    msgSuccess('已改约（原期限保留）')
    await loadAll()
  } catch { /* 拦截器已提示 */ }
}

onMounted(loadAll)
</script>

<style scoped>
.workspace-maintenance { display: grid; gap: 14px; }
.panel { padding: 14px 16px; }
.panel h3 { margin: 0 0 10px; font-size: 14px; }
.hint { font-size: 12px; color: var(--text-muted); font-weight: normal; }
.toolbar { margin-bottom: 10px; }
.sample-steps { margin-bottom: 12px; }
</style>
