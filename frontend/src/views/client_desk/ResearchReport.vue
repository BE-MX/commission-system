<template>
  <div v-if="report?.status === 'ready'" class="report">
    <div class="verdict panel">
      <div class="head"><span class="eyebrow">背调结论</span><span class="muted">{{ meta }}</span></div>
      <p>{{ report.verdict }}</p>
    </div>
    <section v-for="section in report.sections" :key="section.key" class="panel">
      <h4>{{ section.label }}</h4>
      <ul><li v-for="(statement, index) in section.statements" :key="index">{{ statement }}</li></ul>
    </section>
    <button v-if="report.event_key" type="button" class="link-button" @click="$emit('evidence', report.event_key)">查看背调来源 ↘</button>
  </div>
  <div v-else class="empty-state" role="status">
    <h3>无背调结果</h3>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { formatBeijingDate } from '@/utils/datetime'

const props = defineProps({ report: { type: Object, default: null } })
defineEmits(['evidence'])
const meta = computed(() => [
  props.report?.generated_at && formatBeijingDate(props.report.generated_at),
  props.report?.source_count ? `${props.report.source_count} 条来源` : '',
  props.report?.reviewed ? '已审核' : '',
].filter(Boolean).join(' · '))
</script>

<style src="./board.css" scoped></style>
<style scoped>
.report { display: grid; gap: 12px; }
.verdict { border-color: var(--tag-gold-border); background: linear-gradient(145deg, var(--tag-gold-bg), var(--card-bg) 72%); }
.head { display: flex; justify-content: space-between; gap: 10px; }
.eyebrow { color: var(--button-primary-text); font: 700 11px var(--font-display); letter-spacing: 0.1em; }
.verdict p { margin: 8px 0 0; font-size: 15px; line-height: 1.7; }
ul { margin: 0; padding-left: 18px; }
li { margin: 4px 0; line-height: 1.7; color: var(--text-secondary); overflow-wrap: anywhere; }
.panel + .panel { margin-top: 0; }
.report > .link-button { justify-self: start; }
</style>
