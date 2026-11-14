<template>
  <svg class="churn-deck" :class="{ 'is-compact': compact }" :viewBox="viewBox" role="img" :aria-label="label" preserveAspectRatio="xMidYMid meet">
    <rect :x="box.x" :y="box.y" :width="box.w" :height="box.h" class="churn-deck__sea" />
    <polygon :points="hull" class="churn-deck__hull" />
    <g v-for="(region, index) in model.regions" :key="region.key">
      <rect :x="region.x0 - DECK.GAP / 4" :y="-DECK.HALF" :width="region.len + DECK.GAP / 2" :height="DECK.HALF * 2"
            :class="['churn-deck__bay', { 'is-alt': index % 2, 'is-focus': focus === region.key }]"
            @click="!compact && $emit('focus', region.key)" />
      <rect v-for="n in stackCells(region)" :key="n" :x="region.x0 + (n - 1) * DECK.PITCH + 0.3" :y="-0.6" :width="DECK.PITCH - 0.6" height="1.2"
            class="churn-deck__stack" />
      <text v-if="!compact" :x="region.xc" :y="-DECK.HALF - 1.2" class="churn-deck__label">{{ region.key }}</text>
    </g>
    <template v-for="item in shown" :key="item.id">
      <rect :x="item.x - size(item) / 2" :y="item.z - 0.5 + (item.tier === 'fallen' ? 0 : item.stack * 0.18)" :width="size(item)" height="1"
            :class="['churn-deck__box', `is-${item.tier}`, { 'is-selected': item.id === selectedId, 'is-dim': dim(item) }]"
            :tabindex="compact ? -1 : undefined" @click="!compact && $emit('select', item)" />
    </template>
  </svg>
</template>
<script setup>
import { computed } from 'vue'
import { DECK } from './shipLayout'

const props = defineProps({
  model: { type: Object, required: true }, version: { type: Number, default: 0 },
  compact: Boolean, selectedId: { type: Number, default: null }, focus: { type: String, default: null },
  filter: { type: Function, default: null }, label: { type: String, default: '客户流失态势甲板俯视图' },
})
defineEmits(['select', 'focus'])
const pad = computed(() => (props.compact ? 4 : 10))
const box = computed(() => {
  const half = props.model.length / 2
  const x = -half - 10 - pad.value, w = props.model.length + 20 + pad.value * 2
  const zMax = DECK.HALF + (props.compact ? 7 : 14)
  return { x, y: -zMax, w, h: zMax * 2 }
})
const viewBox = computed(() => `${box.value.x} ${box.value.y} ${box.value.w} ${box.value.h}`)
const hull = computed(() => {
  const half = props.model.length / 2, h = DECK.HALF + 0.5
  return [[-half - 9, -h], [half + 1.5, -h], [half + 11, 0], [half + 1.5, h], [-half - 9, h], [-half - 10, 0]].map(p => p.join(',')).join(' ')
})
// version 只用来让父级在原地改条目后触发重算
const shown = computed(() => (props.version, props.model.items.filter(item => item.visible
  && (!props.compact || item.tier !== 'fallen' || Math.abs(item.z) < DECK.HALF + 7))))
function stackCells(region) { return Math.min(region.cols, Math.ceil(region.stackCount / 4)) }
function size(item) { return item.level === 'S级' || item.level === 'A级' ? 1.45 : item.level ? 1.05 : 0.8 }
function dim(item) { return props.filter ? !props.filter(item) : false }
</script>
<style scoped>
.churn-deck { display: block; width: 100%; height: 100%; }
.churn-deck__sea { fill: var(--churn-sea); }
.churn-deck__hull { fill: var(--churn-hull); }
.churn-deck__bay { fill: var(--churn-deck); }
.churn-deck__bay.is-alt { fill: var(--churn-deck-alt); }
.churn-deck:not(.is-compact) .churn-deck__bay { cursor: pointer; }
.churn-deck__bay.is-focus { stroke: var(--churn-structure); stroke-width: 0.15; }
.churn-deck__stack { fill: var(--churn-stable); opacity: 0.75; }
.churn-deck__label { fill: var(--churn-structure); font-size: 1.3px; text-anchor: middle; }
.churn-deck__box { stroke: var(--churn-edge); stroke-opacity: 0.45; stroke-width: 0.06; }
.churn-deck:not(.is-compact) .churn-deck__box { cursor: pointer; }
.churn-deck__box.is-stable { fill: var(--churn-stable); }
.churn-deck__box.is-warning { fill: var(--churn-warning); }
.churn-deck__box.is-critical { fill: var(--churn-critical); }
.churn-deck__box.is-fallen { fill: var(--churn-fallen); }
.churn-deck__box.is-selected { stroke: var(--churn-structure); stroke-width: 0.25; }
.churn-deck__box.is-dim { opacity: 0.18; }
</style>
