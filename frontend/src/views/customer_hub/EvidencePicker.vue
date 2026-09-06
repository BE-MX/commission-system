<template>
  <section class="evidence-picker" :aria-label="kind === 'fact' ? '事实证据' : '事件证据'">
    <div class="picker-toolbar"><el-input v-model="searchForm.keyword" clearable :placeholder="kind === 'fact' ? '搜索证据主题' : '搜索沟通事件'" @keyup.enter="handleSearch" @clear="handleSearch" /><GlassButton variant="secondary" left-icon="Search" :loading="loading" @click="handleSearch">查询</GlassButton></div>
    <p v-if="!readonly" class="hint">已选 {{ modelValue.length }} 条；切换分页会保留选择。<el-button v-if="modelValue.length" link @click="$emit('update:modelValue', [])">清空</el-button></p>
    <p v-if="opportunityId && kind === 'event'" class="hint">仅可选择与本机会及目标阶段匹配的沟通记录；如没有可选项，请先处理该机会关联的客户待办并登记结果。</p>
    <el-alert v-if="error" type="error" title="证据加载失败，请重试。" :closable="false" />
    <div v-else v-loading="loading" class="evidence-list">
      <article v-for="item in list" :key="item.id">
        <el-checkbox v-if="!readonly" :model-value="modelValue.includes(item.id)" :disabled="disabled || !item.selectable" :aria-label="`选择${profileFieldLabel(item.title)}`" @change="selected => toggle(item.id, selected)" />
        <div><strong>{{ profileFieldLabel(item.title) }}</strong><p>{{ item.summary || readableValue(item.value) }}</p><span class="hint">{{ sourceLabels[item.source] || item.source }} · {{ formatBeijingDateTime(item.occurred_at, { seconds: false }) }} · {{ item.selectable ? '可用' : item.unavailable_reason || '已失效，不可选' }}<template v-if="item.fact_layer"> · {{ factLayerLabels[item.fact_layer] }} · {{ verificationLabels[item.verification_status] }}</template></span><a v-if="item.source_url" :href="item.source_url" target="_blank" rel="noopener noreferrer">查看来源</a></div>
      </article>
      <el-empty v-if="!loading && !list.length" description="没有可见证据" :image-size="50" />
    </div>
    <el-pagination v-model:current-page="page" :page-size="pageSize" :total="total" layout="total, prev, pager, next" @current-change="handlePageChange" />
  </section>
</template>
<script setup>
import { watch } from 'vue'
import { listCustomerEvidence } from '@/api/customerHub'
import { formatBeijingDateTime } from '@/utils/datetime'
import { useOperationsList } from './composables/useOperationsList'
import { readableValue, sourceLabels, factLayerLabels, verificationLabels } from './operationsPresentation'
import { profileFieldLabel } from './customerHubPresentation'
const props = defineProps({ customerId: { type: Number, required: true }, kind: { type: String, default: 'fact' }, modelValue: { type: Array, default: () => [] }, readonly: Boolean, disabled: Boolean, opportunityId: { type: Number, default: null }, targetStatus: { type: String, default: null } })
const emit = defineEmits(['update:modelValue'])
const { loading, list, total, page, pageSize, searchForm, error, handleSearch, handlePageChange } = useOperationsList(params => listCustomerEvidence(props.customerId, { ...params, kind: props.kind, ...(props.opportunityId ? { opportunity_id: props.opportunityId, target_status: props.targetStatus } : {}) }), { pageSize: 10, searchForm: { keyword: '' } })
watch(() => [props.customerId, props.kind, props.opportunityId, props.targetStatus], () => { searchForm.keyword = ''; emit('update:modelValue', []); handleSearch() })
watch(list, rows => {
  if (props.readonly || props.disabled) return
  const unavailable = new Set(rows.filter(item => !item.selectable).map(item => item.id))
  if (props.modelValue.some(id => unavailable.has(id))) emit('update:modelValue', props.modelValue.filter(id => !unavailable.has(id)))
})
function toggle(id, selected) { emit('update:modelValue', selected ? [...new Set([...props.modelValue, id])] : props.modelValue.filter(value => value !== id)) }
</script>
<style scoped>.evidence-picker { display: grid; gap: 10px; width: 100%; }.picker-toolbar { display: flex; gap: 8px; }.evidence-list article { display: flex; align-items: start; gap: 10px; padding: 12px 0; border-bottom: 1px solid var(--border-color); }.evidence-list article > div { min-width: 0; }.evidence-list p { margin: 6px 0; white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.6; }.hint { font-size: 12px; color: var(--text-muted); margin: 0; }.evidence-list a { margin-left: 8px; color: var(--color-primary); }.el-pagination { overflow-x: auto; }</style>
