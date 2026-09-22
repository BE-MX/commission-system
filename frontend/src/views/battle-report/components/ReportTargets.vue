<template>
  <section class="table-card battle-panel">
    <div class="battle-section-title"><h3>周期目标填报</h3><span>{{ report.start_date }} — {{ report.end_date }} · USD</span></div>
    <el-alert type="info" :closable="false" :title="`截止时间：${formatBeijingDateTime(report.target_deadline)}（北京时间）。${report.can_admin ? '管理员可代录，截止后更正需填写原因。' : '仅可修改本人目标；小组目标自动汇总。'}`" />
    <el-alert v-if="error" type="error" :closable="false" :title="error" />
    <el-table :data="members" class="list-table" border>
      <el-table-column prop="user_name" label="业务员" min-width="110" max-width="160" show-overflow-tooltip />
      <el-table-column prop="team" label="业务组" min-width="120" max-width="160" show-overflow-tooltip />
      <el-table-column label="目标 / USD" min-width="200" max-width="260"><template #default="{ row }"><el-input v-if="row.can_edit" v-model="values[row.id]" :disabled="saving" :aria-label="`${row.user_name}的目标`" placeholder="填写金额" inputmode="decimal" /><span v-else>{{ row.target_usd == null ? '待填报' : money(row.target_usd) }}</span></template></el-table-column>
      <el-table-column label="填报状态" min-width="100" max-width="140"><template #default="{ row }"><el-tag size="small" effect="plain" :type="row.target_usd == null ? 'warning' : 'success'">{{ row.target_usd == null ? '待填报' : '已填报' }}</el-tag></template></el-table-column>
    </el-table>
    <div v-if="report.can_admin" class="battle-reason"><el-input v-model="reason" maxlength="500" placeholder="代录或更正原因（截止后必填）" aria-label="目标更正原因" /></div>
    <div class="battle-section-title"><span>保存后更新本人、小组及战报完成进度；留存修改记录。</span><GlassButton v-any-permission="['battle_report:write', 'battle_report:admin']" variant="primary" :loading="saving" :disabled="!members.some(m => m.can_edit)" @click="save">保存目标</GlassButton></div>
  </section>
</template>
<script setup>
import { computed, reactive, ref, watch } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import { battleReportApi } from '@/api/battleReport'
import { formatBeijingDateTime } from '@/utils/datetime'
import { msgSuccess } from '@/utils/feedback'
import { errorText, money, targetChanges } from '../helpers'
const props = defineProps({ report: { type: Object, required: true }, team: { type: String, default: '' } })
const emit = defineEmits(['saved'])
const members = computed(() => props.report.members.filter(m => !props.team || m.team === props.team))
const values = reactive({}), reason = ref(''), saving = ref(false), error = ref('')
watch(() => props.report, report => { for (const m of report.members) values[m.id] = m.target_usd ?? '' }, { immediate: true })
async function save() {
  if (saving.value) return
  error.value = ''
  try {
    const targets = targetChanges(members.value, values)
    if (!targets.length) { error.value = '请填写或修改目标金额'; return }
    saving.value = true
    await battleReportApi.targets(props.report.id, { targets, reason: reason.value.trim() })
    msgSuccess('保存目标'); reason.value = ''; emit('saved')
  } catch (e) { error.value = errorText(e) } finally { saving.value = false }
}
</script>
