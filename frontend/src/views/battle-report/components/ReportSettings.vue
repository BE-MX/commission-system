<template>
  <el-dialog :model-value="modelValue" :title="report ? '战报设置' : '新建临时战报'" width="760px" append-to-body :close-on-click-modal="false" @update:model-value="$emit('update:modelValue', $event)">
    <ListPageStatus v-if="participantsResource.error.value" :paged="false" :error="participantsResource.errorMessage.value" :loading="loading" :has-data="participantsResource.hasData.value" @retry="loadParticipants" />
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-form label-position="top" v-loading="loading" @submit.prevent="save">
      <div class="battle-form-grid">
        <el-form-item label="战报名"><el-input v-model="form.name" maxlength="100" placeholder="例如：九月冲刺战报" /></el-form-item>
        <el-form-item label="汇总可见范围"><el-select v-model="form.visibility"><el-option label="本活动参与人互看汇总" value="activity" /><el-option label="仅本组汇总" value="team" /><el-option label="仅本人汇总" value="self" /></el-select></el-form-item>
        <el-form-item label="开始日期"><el-date-picker v-model="form.start_date" type="date" value-format="YYYY-MM-DD" /></el-form-item>
        <el-form-item label="结束日期"><el-date-picker v-model="form.end_date" type="date" value-format="YYYY-MM-DD" /></el-form-item>
        <el-form-item label="目标填报截止时间（北京时间）"><el-date-picker v-model="form.target_deadline" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" /></el-form-item>
        <el-form-item label="统计口径"><span>订单核算日期 · USD · 活动小组</span></el-form-item>
      </div>
      <el-form-item label="参与业务员（有效 OKKI 绑定）"><el-select v-model="selected" multiple filterable placeholder="选择参与人" @change="syncMembers"><el-option v-for="person in options" :key="person.ark_user_id" :label="`${person.user_name} · ${person.team || '未分组'}`" :value="person.ark_user_id" /></el-select></el-form-item>
      <div class="table-card"><el-table :data="form.members" class="list-table" border v-sticky-scrollbar><el-table-column label="业务员" min-width="120" max-width="160"><template #default="{ row }">{{ nameOf(row.ark_user_id) }}</template></el-table-column><el-table-column label="本次活动小组" min-width="220" max-width="300"><template #default="{ row }"><el-input v-model="row.team" maxlength="100" :aria-label="`${nameOf(row.ark_user_id)}的活动组`" placeholder="填写组名，相同组名合并统计" /></template></el-table-column><el-table-column label="组长（可看本组订单）" min-width="230" max-width="280"><template #default="{ row }"><el-checkbox v-model="row.is_captain" :aria-label="`${nameOf(row.ark_user_id)}作为组长`">组长</el-checkbox></template></el-table-column></el-table></div>
      <p class="battle-muted">组别和人员保存为本次活动快照。未出现在名单中的人员，请先检查外部账号绑定。</p>
      <template v-if="report"><el-alert type="warning" :closable="false" title="配置更正将重算整个战报周期，并保留审计记录。旧页面的目标提交会失效；已有成员的目标保留，请核对是否仍适用于新周期。" /><el-form-item label="更正原因（已开始战报必填）"><el-input v-model="form.reason" maxlength="500" placeholder="说明周期、名单或分组调整的原因" /></el-form-item></template>
    </el-form>
    <template #footer><GlassButton :disabled="saving" @click="$emit('update:modelValue', false)">取消</GlassButton><GlassButton v-permission="'battle_report:admin'" variant="primary" :loading="saving" :disabled="loading || !!participantsResource.error.value || !participantsResource.hasLoaded.value" @click="save">{{ report ? '保存并重算' : '保存草稿' }}</GlassButton></template>
  </el-dialog>
</template>
<script setup>
import { useAsyncResource } from '@/composables/useAsyncResource'
import ListPageStatus from '@/components/ListPageStatus.vue'
import { reactive, ref, watch } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import { battleReportApi } from '@/api/battleReport'
import { currentBeijingDate } from '@/utils/datetime'
import { msgSuccess } from '@/utils/feedback'
import { addDays, errorText } from '../helpers'
const props = defineProps({ modelValue: Boolean, report: { type: Object, default: null } })
const emit = defineEmits(['update:modelValue', 'saved'])
const participantsResource = useAsyncResource(async ({ members }, { signal }) => {
  const data = await battleReportApi.participants({ signal, suppressToast: true })
  const items = [...(data.items || [])]
  for (const member of members) if (!items.some(item => item.ark_user_id === member.ark_user_id)) items.push(member)
  return items
}, { initialData: [] })
const options = participantsResource.data, loading = participantsResource.loading
const selected = ref([]), saving = ref(false), error = ref('')
const form = reactive({ name: '', start_date: '', end_date: '', target_deadline: '', visibility: 'activity', members: [], reason: '' })
let scopeVersion = 0
function loadParticipants() { return participantsResource.load({ members: props.report?.members || [] }) }
const nameOf = id => options.value.find(p => p.ark_user_id === id)?.user_name || `账号 ${id}`
watch(() => [props.modelValue, props.report?.id], ([open]) => {
  scopeVersion++
  participantsResource.clear()
  if (!open) return
  error.value = ''
  const today = currentBeijingDate(), report = props.report
  Object.assign(form, report ? { name: report.name, start_date: report.start_date, end_date: report.end_date, target_deadline: report.target_deadline, visibility: report.visibility, reason: '', members: report.members.map(m => ({ ark_user_id: m.ark_user_id, team: m.team, is_captain: m.is_captain })) } : { name: '', start_date: today, end_date: addDays(today, 13), target_deadline: `${today}T23:59:59`, visibility: 'activity', members: [], reason: '' })
  selected.value = form.members.map(m => m.ark_user_id)
  void loadParticipants()
}, { flush: 'sync' })
function syncMembers(ids) {
  form.members = ids.map(id => form.members.find(m => m.ark_user_id === id) || { ark_user_id: id, team: options.value.find(p => p.ark_user_id === id)?.team || '', is_captain: false })
}
async function save() {
  if (saving.value || loading.value || participantsResource.error.value || !participantsResource.hasLoaded.value) return
  error.value = ''
  if (!form.name.trim() || !form.start_date || !form.end_date || !form.target_deadline || !form.members.length || form.members.some(m => !m.team.trim())) { error.value = '请填写名称、周期、截止时间，并为至少一位参与人填写组别'; return }
  saving.value = true
  const scope = scopeVersion, report = props.report
  const id = report?.id, version = report?.version
  try {
    const payload = { ...form, members: form.members.map(m => ({ ...m, team: m.team.trim() })) }
    if (!report) delete payload.reason
    const result = report ? await battleReportApi.update(id, { ...payload, version }) : await battleReportApi.create(payload)
    msgSuccess(report ? '保存设置' : '创建草稿')
    if (scope === scopeVersion) { emit('saved', result.id); emit('update:modelValue', false) }
  } catch (e) { if (scope === scopeVersion) error.value = errorText(e) } finally { saving.value = false }
}
</script>
