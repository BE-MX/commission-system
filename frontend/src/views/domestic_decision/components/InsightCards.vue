<template><div class="insight-cards"><article v-for="group in groups" :key="group.key" class="insight-card"><header><span class="insight-marker">{{ group.customer_id ? '客户' : '口径' }}</span><h3>{{ customerName(group.customer_id) || group.reasons[0].title }}</h3></header><section v-for="reason in group.reasons" :key="reason.rule_key"><h4>{{ reason.title }}</h4><p>{{ reason.explanation }}</p><p class="next-step">{{ reason.next_step }}</p><div class="action-bar"><GlassButton v-if="reason.evidence_refs?.length" variant="link" @click="$emit('evidence', reason.evidence_refs)">查看事实证据</GlassButton><GlassButton v-if="group.customer_id" variant="link" @click="$emit('customer', group.customer_id)">客户画像</GlassButton><GlassButton v-if="group.customer_id" v-permission="'domestic_decision_action:write'" variant="link" :disabled="busy" @click="$emit('action', reason)">加入内部行动</GlassButton></div></section><footer>规则事实 · {{ label(group.reasons[0].evidence_grade || 'individual') }} · {{ group.reasons[0].rule_version || '当前规则' }}</footer></article><el-empty v-if="!groups.length" description="当前范围未触发需要跟进的规则" :image-size="64" /></div></template>
<script setup>
import { computed } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import { groupedInsights, label } from '../state'
const props = defineProps({ insights: { type: Array, default: () => [] }, customers: { type: Array, default: () => [] }, busy: Boolean })
defineEmits(['evidence', 'customer', 'action'])
const groups = computed(() => groupedInsights(props.insights))
function customerName(id) { return props.customers.find(row => row.customer_id === id)?.shop_name }
</script>
