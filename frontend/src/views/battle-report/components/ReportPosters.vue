<template>
  <el-dialog :model-value="modelValue" title="战报海报" width="min(1080px, 96vw)" destroy-on-close @update:model-value="$emit('update:modelValue', $event)">
    <div v-loading="loading" class="poster-settings">
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
      <template v-if="config">
        <el-form label-position="top" :disabled="saving || generating || report.status === 'archived'">
          <el-form-item label="计时工作日">
            <el-date-picker v-model="dates" type="dates" value-format="YYYY-MM-DD" format="MM-DD" placeholder="选择战报周期内的工作日" />
          </el-form-item>
          <p class="poster-help">共 {{ dates?.length || 0 }} 个工作日，每个工作日北京时间 16:00 累计 {{ dailyStep }} 个百分点，最后一天达到 100%。完成率严格高于时间进度为绿色，相等或落后为红色。</p>
          <el-form-item label="钉钉群定时推送">
            <el-switch v-model="enabled" :disabled="!config.push_ready || report.visibility !== 'activity'" />
            <span class="poster-switch-label">活动周期内每天 {{ config.send_times.join('、') }} 各推送团队和个人海报至「{{ config.group_name }}」</span>
          </el-form-item>
          <el-alert v-if="!config.push_ready" type="warning" :closable="false" title="尚未配置战报专用群机器人及公网海报地址，当前可预览下载，不能开启自动推送。" />
          <el-alert v-else-if="report.visibility !== 'activity'" type="warning" :closable="false" title="群海报展示全部参与人；须将战报可见范围设为全活动后才能启用推送。" />
          <el-alert v-else-if="report.status === 'draft'" type="info" :closable="false" title="草稿可保存推送设置，发布战报后才会按时发送。" />
          <p class="poster-help">非工作日仍按时推送，时间进度不增加。归档或活动结束后停止发送。</p>
          <GlassButton v-permission="'battle_report:admin'" variant="primary" :loading="saving" :disabled="generating || report.status === 'archived'" @click="save">保存设置</GlassButton>
        </el-form>
        <div class="poster-toolbar"><GlassButton v-permission="'battle_report:admin'" :loading="generating" :disabled="saving || dirty" @click="preview">生成两张海报</GlassButton><span>{{ dirty ? '请先保存修改，再生成海报' : '预览和下载不会发送群消息' }}</span></div>
        <p v-if="calculatedAt" class="poster-help">同一数据快照：{{ formatBeijingDateTime(calculatedAt) }}（北京时间）</p>
        <div v-if="images" class="poster-grid">
          <article v-for="kind in ['team', 'personal']" :key="kind"><h3>{{ kind === 'team' ? '团队' : '个人' }}海报</h3><a :href="images[kind]" :download="`${report.name}-${kind}.png`">下载完整海报</a><el-image :src="images[kind]" :preview-src-list="[images[kind]]" fit="contain" /></article>
        </div>
        <h3>最近推送记录</h3>
        <el-empty v-if="!config.history.length" description="暂无推送记录" :image-size="60" />
        <el-table v-else :data="config.history" class="list-table" border>
          <el-table-column label="推送时段" min-width="160"><template #default="{ row }">{{ row.date }} {{ row.slot }}</template></el-table-column>
          <el-table-column v-for="kind in ['team', 'personal']" :key="kind" :label="kind === 'team' ? '团队海报' : '个人海报'" min-width="180"><template #default="{ row }"><el-tag :type="statusType(row.deliveries[kind].status)">{{ statusLabels[row.deliveries[kind].status] || row.deliveries[kind].status }}</el-tag><p v-if="row.deliveries[kind].error" class="poster-help">{{ row.deliveries[kind].error }}</p></template></el-table-column>
        </el-table>
      </template>
    </div>
  </el-dialog>
</template>
<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import { battleReportApi } from '@/api/battleReport'
import { formatBeijingDateTime } from '@/utils/datetime'
import { msgSuccess } from '@/utils/feedback'
import { errorText } from '../helpers'
const props = defineProps({ modelValue: Boolean, report: { type: Object, required: true } })
const emit = defineEmits(['update:modelValue', 'saved'])
const config = ref(null), dates = ref([]), enabled = ref(false), loading = ref(false), saving = ref(false), generating = ref(false), error = ref(''), images = ref(null), calculatedAt = ref('')
let alive = true
const dailyStep = computed(() => dates.value?.length ? (Math.floor(10000 / dates.value.length) / 100).toFixed(2) : '—')
const dirty = computed(() => config.value && (enabled.value !== config.value.push_enabled || JSON.stringify([...(dates.value || [])].sort()) !== JSON.stringify(config.value.work_dates)))
const statusLabels = { pending: '等待发送', sending: '发送中', sent: '已发送', failed: '失败待重试', uncertain: '结果待人工核对' }
const statusType = value => value === 'sent' ? 'success' : ['failed', 'uncertain'].includes(value) ? 'danger' : 'info'
function apply(value) { config.value = value; dates.value = [...value.work_dates]; enabled.value = value.push_enabled }
async function load() { loading.value = true; try { const result = await battleReportApi.posterConfig(props.report.id); if (alive) apply(result) } catch (e) { if (alive) error.value = errorText(e) } finally { if (alive) loading.value = false } }
async function save() {
  if (!dates.value?.length) { error.value = '请至少选择一个工作日'; return }
  saving.value = true; error.value = ''
  try { const result = await battleReportApi.savePosterConfig(props.report.id, { version: config.value.version, work_dates: dates.value, push_enabled: enabled.value }); if (alive) { apply(result); images.value = null; msgSuccess('保存海报设置'); emit('saved') } }
  catch (e) { if (alive) error.value = errorText(e) } finally { if (alive) saving.value = false }
}
async function preview() {
  generating.value = true; error.value = ''; images.value = null
  try { const result = await battleReportApi.previewPosters(props.report.id); if (alive) { images.value = result.images; calculatedAt.value = result.calculated_at } }
  catch (e) { if (alive) error.value = errorText(e) } finally { if (alive) generating.value = false }
}
onMounted(load)
onUnmounted(() => { alive = false })
</script>
<style scoped>
.poster-settings{display:grid;gap:16px}.poster-help,.poster-toolbar>span{color:var(--text-secondary);font-size:13px;line-height:1.6}.poster-switch-label{margin-left:12px}.poster-toolbar{display:flex;align-items:center;gap:16px;flex-wrap:wrap}.poster-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}.poster-grid article{min-width:0}.poster-grid a{color:var(--color-primary);display:block;margin-bottom:12px}.poster-grid .el-image{width:100%;max-height:650px;overflow:auto}.poster-grid h3{margin-top:0}@media(max-width:700px){.poster-grid{grid-template-columns:1fr}}
</style>
