<template>
  <component :is="interactive ? 'button' : 'div'" :type="interactive ? 'button' : undefined"
             class="stats-kpi" :class="`stats-kpi--${tone}`" :style="{ '--stats-index': index }" @click="$emit('click')">
    <el-icon class="stats-kpi__icon" aria-hidden="true"><component :is="icon" /></el-icon>
    <span class="stats-kpi__label">{{ label }}</span>
    <strong class="stats-kpi__value">{{ displayValue }}<small v-if="unit">{{ unit }}</small></strong>
    <span class="stats-kpi__foot">
      <span v-if="delta" class="stats-delta" :class="`stats-delta--${delta.direction}`">{{ delta.text }}<template v-if="!percentagePoints"> 较上期</template></span>
      <span v-if="teamAverage !== null && teamAverage !== undefined">团队均值 {{ teamAverageText }}</span>
      <span v-if="footnote">{{ footnote }}</span>
      <slot />
    </span>
    <el-icon class="stats-kpi__watermark" aria-hidden="true"><component :is="icon" /></el-icon>
  </component>
</template>
<script setup>
import { computed } from 'vue'
import { deltaInfo, percent } from './statsModel'
const props = defineProps({
  label: String, value: [Number, String], unit: String, icon: { type: [Object, Function], required: true },
  tone: { type: String, default: 'gold' }, index: { type: Number, default: 0 },
  current: [Number, String], previous: [Number, String], percentagePoints: Boolean, inverse: Boolean,
  teamAverage: [Number, String], rate: Boolean, footnote: String, interactive: Boolean,
})
const displayValue = computed(() => props.rate ? percent(props.value) : (props.value ?? '—'))
const delta = computed(() => deltaInfo(props.current, props.previous, { percentagePoints: props.percentagePoints, inverse: props.inverse }))
const teamAverageText = computed(() => props.rate ? percent(props.teamAverage) : props.teamAverage)
defineEmits(['click'])
</script>
