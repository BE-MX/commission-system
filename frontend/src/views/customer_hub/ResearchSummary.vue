<template>
  <section class="research-summary">
    <el-alert v-if="detail.content_redacted" type="warning" title="当前研究内容已脱敏，不能作为审核依据。" :closable="false" />
    <template v-else>
      <article><h3>研究结论</h3><p>{{ readableValue(detail.research_summary || result.summary || detail.selection_reason || '研究未提供结论摘要') }}</p></article>
      <article v-for="section in sections" :key="section.key"><h3>{{ section.label }}</h3><p v-if="!section.claims.length">本次研究未提供该方面结论</p><div v-for="(claim, index) in section.claims" :key="index" class="claim"><p>{{ claim.text || claim.claim || claim.statement || readableValue(claim.value ?? claim) }}</p><span v-for="item in claimEvidence(claim)" :key="item.id" class="hint">依据：{{ profileFieldLabel(item.title) }} · {{ sourceLabels[item.source] || item.source }}<a v-if="item.source_url" :href="item.source_url" target="_blank" rel="noopener noreferrer">查看来源</a></span><span v-if="claim.confidence != null" class="hint">研究置信度：{{ claim.confidence }}（不等于开发资格）</span></div></article>
      <article v-if="detail.evidence?.length"><h3>结论依据</h3><div v-for="item in detail.evidence" :key="item.id" class="claim"><strong>{{ profileFieldLabel(item.title) }}</strong><p>{{ readableValue(item.value) }}</p><span class="hint">{{ sourceLabels[item.source] || item.source }} · {{ formatBeijingDateTime(item.occurred_at, { seconds: false }) }} · {{ factLayerLabels[item.fact_layer] }} · {{ verificationLabels[item.verification_status] }} · {{ item.selectable ? '当前可用' : '证据已失效' }}</span><a v-if="item.source_url" :href="item.source_url" target="_blank" rel="noopener noreferrer">查看来源</a></div></article>
    </template>
  </section>
</template>
<script setup>
import { computed } from 'vue'
import { readableValue, sourceLabels, factLayerLabels, verificationLabels } from './operationsPresentation'
import { profileFieldLabel } from './customerHubPresentation'
import { formatBeijingDateTime } from '@/utils/datetime'
const props = defineProps({ detail: { type: Object, required: true } })
const result = computed(() => props.detail.result_json || {})
const sectionLabels = { identity: '客户主体', business_quality: '经营情况', product_fit: '产品适配', supplier_status: '供应商现状', risk: '风险与缺口', strategy: '建议动作' }
const sections = computed(() => Object.entries(sectionLabels).map(([key, label]) => ({ key, label, claims: Array.isArray(result.value.claims) ? result.value.claims.filter(claim => claim.section === key) : result.value[key] ? [result.value[key]] : [] })))
function claimEvidence(claim) {
  const ids = new Set((result.value.citations || []).filter(item => item.claim_id === claim.claim_id).map(item => Number(String(item.evidence_ref).replace('fact:', ''))))
  return (props.detail.evidence || []).filter(item => ids.has(item.id))
}
</script>
<style scoped>.research-summary { display: grid; gap: 12px; }.research-summary article { padding: 14px; border: 1px solid var(--border-color); border-radius: 8px; }.research-summary h3 { margin: 0 0 8px; font-size: 15px; }.research-summary p { margin: 6px 0; line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; color: var(--text-secondary); }.claim + .claim { margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--border-color); }.hint { font-size: 12px; color: var(--text-muted); }.research-summary a { margin-left: 8px; color: var(--color-primary); }</style>
