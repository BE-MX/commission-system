<template><div class="decision-metrics"><div v-for="card in cards" :key="card.key" class="decision-metric" :class="`tone-${card.tone || 'gold'}`"><div class="metric-top"><span class="metric-icon"><component :is="card.icon || DataAnalysis" /></span><span>{{ card.label }}</span></div><strong>{{ card.format === 'money' ? money(data?.[card.key]) : number(data?.[card.key], 1) }}</strong><p>{{ card.note || comparisonText(changes?.[card.key]) }}</p><component :is="card.icon || DataAnalysis" class="metric-watermark" aria-hidden="true" /></div></div></template>
<script setup>
import { DataAnalysis } from '@element-plus/icons-vue'
import { money, number, comparisonText } from '../state'
defineProps({ cards: Array, data: Object, changes: Object })
</script>
