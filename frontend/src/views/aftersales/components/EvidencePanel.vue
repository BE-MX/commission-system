<template>
  <section class="surface-section">
    <div class="section-head">
      <div class="section-title"><el-icon><Picture /></el-icon><span>客户证据</span></div>
      <div class="score" :class="{ sufficient: caseData.evidence_is_sufficient }">{{ caseData.evidence_score || 0 }}%</div>
    </div>
    <el-progress :percentage="caseData.evidence_score || 0" :status="caseData.evidence_is_sufficient ? 'success' : 'warning'" />
    <div v-if="!caseData.evidence_is_sufficient && caseData.evidence_missing_items_json?.length" class="missing-box">
      <strong>还缺：</strong>{{ caseData.evidence_missing_items_json.join('、') }}
      <GlassButton v-if="canRequestWaiver" variant="secondary" left-icon="Stamp" @click="$emit('request-waiver')">申请主管豁免</GlassButton>
    </div>
    <div v-else-if="caseData.evidence_is_sufficient" class="complete-box"><el-icon><CircleCheck /></el-icon> 已达到最低证据要求</div>
    <div v-else class="missing-box">上传证据后，系统会显示完整度和缺失项</div>
    <div v-if="caseData.current_status === 'awaiting_evidence_waiver'" class="waiver-box pending"><strong>证据豁免待直属主管确认</strong><span>{{ caseData.evidence_waiver_reason }}</span></div>
    <div v-else-if="caseData.evidence_waiver_approved" class="waiver-box approved"><strong>直属主管已批准证据豁免</strong><span>{{ caseData.evidence_waiver_decision_note }}</span></div>

    <div v-if="!locked" class="upload-row">
      <el-select v-model="evidenceType" placeholder="证据类型">
        <el-option v-for="item in evidenceTypes" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <AppUpload v-model="filesModel" :upload-fn="upload" accept="image/*,video/mp4,video/quicktime,.pdf,.doc,.docx" :max-size-mb="200" :limit="30" button-text="上传证据" />
    </div>
    <div v-else-if="filesModel.length" class="locked-files">
      <a v-for="item in filesModel" :key="item.id" href="#" @click.prevent="$emit('download', item)">{{ item.name }}</a>
    </div>

    <el-form label-position="top" class="confirm-form" :disabled="locked">
      <el-form-item label="业务员确认客户证据是否完整">
        <el-radio-group v-model="salesConfirmed">
          <el-radio :value="true">完整</el-radio><el-radio :value="false">不完整</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item v-if="salesConfirmed !== null && salesConfirmed !== caseData.evidence_is_sufficient" label="与系统判断不一致，请说明">
        <el-input v-model="salesNote" type="textarea" :rows="2" />
      </el-form-item>
    </el-form>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import AppUpload from '@/components/AppUpload.vue'

const props = defineProps({ caseData: { type: Object, required: true }, files: { type: Array, default: () => [] }, locked: Boolean, canRequestWaiver: Boolean, uploadFn: { type: Function, required: true } })
const emit = defineEmits(['update:files', 'remove', 'download', 'request-waiver', 'update:sales-confirmed', 'update:sales-note'])
const evidenceType = ref('overview_image')
const evidenceTypes = [
  { value: 'overview_image', label: '问题全景图' }, { value: 'closeup_image', label: '问题近景图' },
  { value: 'video', label: '问题视频' }, { value: 'batch_label', label: '包装/批次标签' },
  { value: 'care_attachment', label: '护理/存储附件' }, { value: 'other', label: '其他文件' },
]
const filesModel = computed({
  get: () => props.files,
  set: next => {
    const removed = props.files.find(item => !next.some(candidate => candidate.id === item.id))
    if (removed) emit('remove', removed)
    emit('update:files', next)
  },
})
const salesConfirmed = computed({ get: () => props.caseData.sales_evidence_confirmed ?? null, set: value => emit('update:sales-confirmed', value) })
const salesNote = computed({ get: () => props.caseData.sales_evidence_note || '', set: value => emit('update:sales-note', value) })
const upload = file => props.uploadFn(file, evidenceType.value)
</script>

<style scoped>
.surface-section { padding: 18px; border: 1px solid var(--border-color); border-radius: var(--card-radius); background: var(--card-bg); box-shadow: var(--card-shadow); }
.section-head, .section-title { display: flex; align-items: center; }
.section-head { justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.section-title { gap: 8px; color: var(--text-primary); font: 700 15px/1.3 var(--font-display); }
.score { color: var(--color-warning-text); font-weight: 700; font-variant-numeric: tabular-nums; }.score.sufficient { color: var(--color-success-text); }
.missing-box, .complete-box { margin-top: 10px; padding: 10px 12px; border-radius: 8px; font-size: 13px; }
.missing-box { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; color: var(--color-warning-text); background: var(--color-warning-bg); }.missing-box :deep(button) { margin-left: auto; }.complete-box { display: flex; align-items: center; gap: 6px; color: var(--color-success-text); background: var(--color-success-bg); }
.waiver-box { display: flex; flex-direction: column; gap: 4px; margin-top: 10px; padding: 10px 12px; border-radius: 8px; font-size: 12px; }.waiver-box.pending { color: var(--color-warning-text); background: var(--color-warning-bg); }.waiver-box.approved { color: var(--color-success-text); background: var(--color-success-bg); }.waiver-box span { color: var(--text-secondary); }
.upload-row { display: grid; grid-template-columns: 180px 1fr; gap: 12px; align-items: start; margin-top: 16px; }
.locked-files { display: flex; flex-wrap: wrap; gap: 8px 16px; margin-top: 14px; }.locked-files a { color: var(--color-primary); font-size: 13px; }
.confirm-form { margin-top: 16px; }.confirm-form :deep(.el-form-item:last-child) { margin-bottom: 0; }
@media (max-width: 760px) { .upload-row { grid-template-columns: 1fr; } }
</style>
