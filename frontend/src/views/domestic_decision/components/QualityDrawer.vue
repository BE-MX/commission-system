<template>
  <DetailDrawer v-model="open" title="数据质量、口径与治理" :width="760">
    <template v-if="data"><div class="decision-notice">未知值保留，不将缺失历史补零。建议门槛同时考虑记录覆盖和展示指标加权覆盖。</div><section class="decision-panel"><h2>版本与样本</h2><div class="fact-grid"><div><span>完整历史覆盖起点</span><strong>{{ data.meta.coverage_start || '尚未确认' }}</strong></div><div><span>数据截止</span><strong>{{ formatBeijingDateTime(data.meta.data_as_of, { seconds: false }) }}</strong></div><div><span>指标版本</span><strong>{{ data.meta.metric_version }}</strong></div><div><span>规则版本</span><strong>{{ data.meta.rule_version }}</strong></div><div><span>订单 / 明细 / 客户样本</span><strong>{{ data.meta.sample_size.orders }} / {{ data.meta.sample_size.items }} / {{ data.meta.sample_size.customers }}</strong></div><div><span>强建议覆盖门槛</span><strong>{{ percent(data.quality.quality_threshold) }}</strong></div></div><p class="decision-note">映射版本：{{ Object.entries(data.meta.mapping_version || {}).map(([id, version]) => `${id}:v${version}`).join(' · ') || '无已保存映射' }}</p><p v-for="note in data.meta.warnings" :key="note" class="decision-note">{{ note }}</p></section>
    <section class="decision-panel"><h2>产品属性完整度</h2><DecisionTable :rows="coverageRows" :columns="coverageColumns" :paginate="false" /></section><section class="decision-panel"><h2>整单 / 明细对账</h2><DecisionTable :rows="data.quality.order_reconciliation" :columns="reconciliationColumns" action="整单证据" @open="row => $emit('evidence', [{ type: 'orders', id: row.order_id }])" /><h3>有效经营统计排除项</h3><DecisionTable :rows="excludedRows" :columns="[{ key: 'label', label: '原因' }, { key: 'count', label: '排除订单数', format: 'number' }]" :paginate="false" /></section>
    <section v-if="data.finance?.anomalies?.length" class="decision-panel"><h2>资金账链异常</h2><DecisionTable :rows="data.finance.anomalies" :columns="anomalyColumns" /></section>
    </template>
    <section class="decision-panel" v-permission="'domestic_decision:admin'"><div class="section-heading"><h2>分析标准维护</h2><GlassButton :loading="settingsLoading" @click="loadSettings">加载 / 刷新配置</GlassButton></div><p class="decision-note">只维护分析映射与版本化规则，不修改原始订单。保存后刷新筛选值域与整组分析。</p><el-alert v-if="settingsError" type="error" :title="settingsError" :closable="false" />
    <template v-if="settings"><h3>颜色、工艺与尺寸映射</h3><DecisionTable :rows="settings.mappings" :columns="mappingColumns" action="编辑" @open="editMapping" /><el-form label-position="top" class="mapping-form"><el-form-item label="属性"><el-select v-model="mapping.property"><el-option label="颜色" value="color" /><el-option label="工艺" value="craft" /><el-option label="尺寸" value="size" /></el-select></el-form-item><el-form-item label="产品范围"><el-select v-model="mapping.product_type"><el-option label="全部" value="" /><el-option label="头套" value="cap" /><el-option label="发片" value="piece" /></el-select></el-form-item><el-form-item label="原始值"><el-input v-model="mapping.raw_value" maxlength="255" /></el-form-item><el-form-item label="分析标准值"><el-input v-model="mapping.standard_value" maxlength="255" /></el-form-item></el-form><div class="action-bar"><GlassButton variant="primary" :loading="saving" :disabled="!mapping.raw_value.trim() || !mapping.standard_value.trim()" @click="saveMapping">保存分析映射</GlassButton><GlassButton @click="resetMapping">清空 / 新增</GlassButton></div><p class="decision-note">发片工艺与尺寸复合值可拆为两项标准映射；自由文本颜色原文仍保留。</p>
    <h3>覆盖与规则配置</h3><div class="config-grid"><label v-for="config in configs" :key="config.key"><span>{{ config.label }} <small>v{{ config.version }}</small></span><el-date-picker v-if="config.key === 'coverage_start'" v-model="config.value" value-format="YYYY-MM-DD" clearable placeholder="未确认" /><el-select v-else-if="config.options" v-model="config.value" multiple filterable><el-option v-for="option in config.options" :key="option.value" :value="option.value" :label="option.label" /></el-select><el-input-number v-else v-model="config.value" :min="config.min" :max="config.max" :step="config.step" :precision="config.precision" /><GlassButton variant="link" :loading="saving" @click="saveConfig(config)">保存</GlassButton></label></div></template>
    </section>
  </DetailDrawer>
</template>
<script setup>
import { computed, reactive, ref, watch } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import DecisionTable from './DecisionTable.vue'
import { domesticDecisionApi as api } from '@/api/domesticDecision'
import { formatBeijingDateTime } from '@/utils/datetime'
import { FIELD_LABELS, percent } from '../state'
const props = defineProps({ modelValue: Boolean, data: Object, options: Object, adminAllowed: Boolean, mutate: Function, failure: Function })
const emit = defineEmits(['update:modelValue', 'evidence', 'refresh'])
const open = computed({ get: () => props.modelValue, set: value => emit('update:modelValue', value) })
const settings = ref(null), settingsLoading = ref(false), settingsError = ref(''), saving = ref(false), configs = ref([])
const mapping = reactive({ property: 'color', product_type: '', raw_value: '', standard_value: '' })
const col = (key, label, format) => ({ key, label, format })
const coverageColumns = [col('label', '属性'), col('applicable_count', '适用明细', 'number'), col('known_count', '已知', 'number'), col('unknown_count', '未知', 'number'), col('not_applicable_count', '不适用', 'number'), col('record_coverage', '记录覆盖', 'percent'), col('amount_coverage', '金额覆盖', 'percent'), col('quantity_coverage', '数量覆盖', 'percent'), col('effective_coverage', '展示指标有效覆盖', 'percent'), { key: 'strong_advice_enabled', label: '建议门槛', get: row => row.strong_advice_enabled ? '通过覆盖门槛' : '仅观察事实' }]
const reconciliationColumns = [col('order_id', '订单ID'), col('header_amount', '整单额', 'money'), col('item_amount', '明细额', 'money'), col('difference', '差异', 'money')]
const mappingColumns = [col('property', '属性'), col('product_type', '产品范围'), col('raw_value', '原文'), col('standard_value', '分析标准'), col('version', '版本')]
const anomalyColumns = [col('customer_id', '客户ID'), col('type', '异常'), col('ledger_id', '流水ID'), col('difference', '差异', 'money')]
const coverageRows = computed(() => Object.entries(props.data?.quality.dimension_coverage || {}).map(([key, row]) => ({ ...row, label: FIELD_LABELS[key] })))
const excludedRows = computed(() => Object.entries(props.data?.quality.excluded_order_counts || {}).map(([key, count]) => ({ label: { deleted: '已删除', production: '生产单', status_0: '草稿', status_4: '已终止', status_5: '待审核', status_6: '已驳回' }[key] || key, count })))
const configSpecs = [
  { key: 'coverage_start', label: '完整历史覆盖起点', initial: null },
  { key: 'aftersales_order_types', label: '售后订单类型', initial: [], dictionary: 'domestic_order_type' },
  { key: 'quality_threshold', label: '强建议属性覆盖门槛', initial: .8, min: .5, max: 1, step: .05, precision: 2 },
  { key: 'dormant_days', label: '沉睡观察天数', initial: 90, min: 30, max: 365, step: 1, precision: 0 },
  { key: 'ai_daily_limit', label: '每日AI请求限额', initial: 10, min: 1, max: 50, step: 1, precision: 0 },
  { key: 'inactive_lifecycle_statuses', label: '不触发经营行动的生命周期', initial: [], dictionary: 'domestic_customer_lifecycle' },
  { key: 'coverage_refund_ratio_limit', label: '覆盖天数允许退款调整占比', initial: .2, min: 0, max: 1, step: .05, precision: 2 },
]
async function loadSettings() {
  if (!props.adminAllowed) return
  settingsLoading.value = true; settingsError.value = ''
  try { settings.value = await api.settings(); configs.value = configSpecs.map(spec => { const current = settings.value.config.find(row => row.key === spec.key); const options = spec.dictionary ? props.options.dictionaries?.[spec.dictionary] || [] : null; return { ...spec, value: JSON.parse(JSON.stringify(current ? current.value : spec.initial)), version: current?.version || 0, ...(options ? { options } : {}) } }) }
  catch (cause) { settingsError.value = props.failure(cause) } finally { settingsLoading.value = false }
}
function resetMapping() { Object.keys(mapping).forEach(key => delete mapping[key]); Object.assign(mapping, { property: 'color', product_type: '', raw_value: '', standard_value: '' }) }
function editMapping(row) { resetMapping(); Object.assign(mapping, { property: row.property, product_type: row.product_type, raw_value: row.raw_value, standard_value: row.standard_value, expected_version: row.version }) }
async function saveMapping() {
  saving.value = true
  try { const existing = settings.value.mappings.find(row => row.property === mapping.property && row.product_type === mapping.product_type && row.raw_value === mapping.raw_value.trim()); const body = { property: mapping.property, product_type: mapping.product_type, raw_value: mapping.raw_value.trim(), standard_value: mapping.standard_value.trim(), ...(existing ? { expected_version: existing.version } : {}) }; await props.mutate(() => api.mapping(body), '分析映射已保存'); resetMapping(); emit('refresh'); await loadSettings() } catch { await loadSettings() } finally { saving.value = false }
}
async function saveConfig(config) {
  saving.value = true
  try { await props.mutate(() => api.config(config.key, { expected_version: config.version, value: config.value ?? null }), '规则配置已保存'); emit('refresh'); await loadSettings() } catch { await loadSettings() } finally { saving.value = false }
}
watch(open, value => { if (value && props.adminAllowed && !settings.value) loadSettings() })
</script>
