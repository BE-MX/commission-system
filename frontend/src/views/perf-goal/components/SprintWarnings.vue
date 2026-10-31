<template>
  <div class="pg-card pg-sprint-summary" :class="{ 'pg-sprint-attention': warnings.length }">
    <div class="pg-card-title"><h2>{{ warnings.length ? `需关注 ${warnings.length} 项` : '冲刺提醒' }}</h2><span v-if="warnings.length" class="pg-note">按当前工作日日均完成速度估算</span></div>
    <p v-if="!warnings.length" class="pg-context-note">{{ sprintEmptyDescription(metrics, timeProgress) }}</p>
    <ul v-else class="pg-sprint-list">
      <li v-for="(w, i) in shownWarnings" :key="`${w.user_id}-${w.metric}-${i}`">
        <strong>{{ w.name || '当前范围' }}</strong>
        <span v-if="w.text">{{ w.text }}</span>
        <template v-else><span>{{ metricMeta(w.metric).name }}距目标 <b>{{ fmtMetric(w.metric, w.gap, { withUnit: !metricMeta(w.metric).money }) }}</b></span><span>预计期末完成率 <b>{{ fmtRate(w.projected_rate) }}</b></span></template>
      </li>
    </ul>
    <GlassButton v-if="warnings.length > 3" variant="link" :aria-expanded="expanded" @click="expanded = !expanded">{{ expanded ? '收起其余提醒' : `展开其余 ${warnings.length - 3} 项提醒` }}</GlassButton>
  </div>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { metricMeta, fmtMetric, fmtRate } from '../helpers'
import { sprintEmptyDescription } from '../displayText'
const props = defineProps({ warnings: { type: Array, default: () => [] }, metrics: { type: Object, default: () => ({}) }, timeProgress: { type: Number, default: null } })
const expanded = ref(false)
const shownWarnings = computed(() => expanded.value ? props.warnings : props.warnings.slice(0, 3))
watch(() => props.warnings, () => { expanded.value = false })
</script>
