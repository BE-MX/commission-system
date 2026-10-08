<template>
  <section class="decision-panel filter-panel" aria-label="分析范围">
    <div class="filter-grid">
      <label class="filter-date">时间范围（北京时间）<el-date-picker v-model="dates" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" :clearable="false" /></label>
      <label>对照周期<el-select v-model="query.comparison_mode"><el-option label="上一等长周期" value="previous" /><el-option label="去年同期" value="year" /><el-option label="不对照" value="none" /></el-select></label>
      <label>客户范围<el-select v-model="query.scope"><el-option label="我的客户" value="mine" /><el-option v-if="permissions.all" label="全部授权客户" value="all" /></el-select></label>
      <label>指定客户<el-select v-model="query.customer_ids" multiple filterable collapse-tags collapse-tags-tooltip placeholder="范围内全部客户"><el-option v-for="row in options.customers" :key="row.value" v-bind="row" /></el-select></label>
      <label v-if="permissions.all">当前负责人<el-select v-model="query.owner_ids" multiple filterable collapse-tags placeholder="全部负责人"><el-option v-for="row in options.owners" :key="row.value" v-bind="row" /></el-select></label>
    </div>
    <details class="advanced-filters"><summary>产品规格、客户属性与订单筛选 <span>{{ activeFilterCount ? `· ${activeFilterCount} 项已选择` : '' }}</span></summary>
      <div class="filter-grid"><label v-for="(values, field) in options.dimensions" :key="field">{{ FIELD_LABELS[field] || field }}<el-select v-model="query.filters[field]" multiple filterable collapse-tags collapse-tags-tooltip placeholder="全部"><el-option v-for="row in values" :key="row.value" :value="row.value" :label="optionLabel(field, row)" /></el-select></label></div>
    </details>
    <div class="action-bar">
      <GlassButton variant="primary" :loading="loading" @click="$emit('apply')">{{ loading ? '分析中…' : '应用筛选' }}</GlassButton>
      <GlassButton @click="reset">重置</GlassButton>
      <GlassButton @click="$emit('refresh')">刷新快照</GlassButton>
      <el-select v-model="selectedView" placeholder="加载已保存视图" clearable class="view-select" @change="loadView"><el-option v-for="view in views" :key="view.id" :value="view.id" :label="`${view.name}${view.shared ? ' · 共享条件' : ''}`" /></el-select>
      <GlassButton @click="viewOpen = true">保存视图</GlassButton>
      <GlassButton @click="$emit('quality')">数据质量与口径</GlassButton>
      <span v-if="meta" class="snapshot">{{ formatBeijingDateTime(meta.data_as_of, { seconds: false }) }} 快照 · {{ meta.sample_size?.orders ?? 0 }} 单</span>
    </div>
    <div v-if="applied" class="filter-chips" aria-label="当前已应用条件"><span>{{ applied.start_date }} — {{ applied.end_date }}</span><span>{{ applied.scope === 'all' ? '全部授权客户' : '我的客户' }}</span><span v-for="(values, field) in applied.filters" :key="field">{{ FIELD_LABELS[field] }}：{{ values.map(value => optionLabel(field, { value, label: value })).join('、') }}</span></div>
    <el-dialog v-model="viewOpen" title="保存分析视图" width="480px" append-to-body>
      <el-form label-position="top"><el-form-item label="视图名称"><el-input v-model="viewForm.name" maxlength="80" /></el-form-item><el-form-item label="时间行为"><el-radio-group v-model="viewForm.time_mode"><el-radio value="rolling">滚动等长周期</el-radio><el-radio value="fixed">固定日期</el-radio></el-radio-group></el-form-item><el-checkbox v-model="viewForm.shared">共享筛选条件</el-checkbox><p class="decision-note">共享的是条件；每位使用者按自己的实时客户权限重新查询，不共享结果数据。</p></el-form>
      <template #footer><GlassButton @click="viewOpen = false">取消</GlassButton><GlassButton variant="primary" :loading="saving" :disabled="!viewForm.name.trim() || !applied" @click="saveView">保存</GlassButton></template>
    </el-dialog>
    <div v-if="selectedOwnedView" class="view-manage"><GlassButton variant="link" @click="updateView">用当前已应用条件更新「{{ selectedOwnedView.name }}」</GlassButton><GlassButton variant="link" link-tone="danger" @click="deleteView">删除此视图</GlassButton></div>
  </section>
</template>
<script setup>
import { computed, reactive, ref } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import { domesticDecisionApi as api } from '@/api/domesticDecision'
import { useAuthStore } from '@/stores/auth'
import { currentBeijingDate, formatBeijingDateTime } from '@/utils/datetime'
import { confirmAction, isFeedbackCancelled } from '@/utils/feedback'
import { applySavedView, defaultQuery, FIELD_LABELS, label } from '../state'
const props = defineProps({ query: Object, applied: Object, options: Object, permissions: Object, loading: Boolean, views: Array, meta: Object, mutate: Function })
const emit = defineEmits(['apply', 'refresh', 'quality', 'views'])
const auth = useAuthStore(), selectedView = ref(null), viewOpen = ref(false), saving = ref(false)
const viewForm = reactive({ name: '', time_mode: 'rolling', shared: false })
const dates = computed({ get: () => [props.query.start_date, props.query.end_date], set: value => { if (value?.length === 2) { props.query.start_date = value[0]; props.query.end_date = value[1] } } })
const activeFilterCount = computed(() => Object.values(props.query.filters).filter(value => value?.length).length)
const selectedOwnedView = computed(() => props.views?.find(view => view.id === selectedView.value && view.owner_user_id === auth.user?.id))
function optionLabel(field, row) {
  const dictionary = props.options.dictionaries?.[`domestic_${field}`] || []
  return dictionary.find(item => item.value === row.value)?.label || label(row.label)
}
function reset() { Object.assign(props.query, defaultQuery(currentBeijingDate())); emit('apply') }
function loadView(id) { const view = props.views.find(row => row.id === id); if (view) { Object.assign(props.query, applySavedView(view, currentBeijingDate(), props.options)); emit('apply') } }
async function saveView() {
  saving.value = true
  try { await props.mutate(() => api.saveView({ ...viewForm, name: viewForm.name.trim(), query: props.applied }), '视图已保存'); viewOpen.value = false; emit('views') } catch { /* shared error UI */ } finally { saving.value = false }
}
async function updateView() {
  const view = selectedOwnedView.value
  if (!view || !props.applied) return
  try { await props.mutate(() => api.updateView(view.id, { name: view.name, time_mode: view.time_mode, shared: view.shared, query: props.applied, expected_version: view.version }), '视图已更新'); emit('views') } catch { emit('views') }
}
async function deleteView() {
  const view = selectedOwnedView.value
  try { await confirmAction(`删除视图「${view.name}」？`, '删除分析视图'); await props.mutate(() => api.deleteView(view.id), '视图已删除'); selectedView.value = null; emit('views') } catch (cause) { if (!isFeedbackCancelled(cause)) emit('views') }
}
</script>
