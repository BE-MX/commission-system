<template>
  <div
    class="gradient-bar"
    :class="`type-${blendType}`"
    :style="barStyle"
  >
    <template v-if="blendType === 'piano'">
      <div
        v-for="(seg, i) in segments"
        :key="i"
        class="piano-segment"
        :style="{ backgroundColor: seg.color, flex: seg.weight }"
      />
    </template>
    <template v-else>
      <div
        v-for="(seg, i) in segments"
        :key="i"
        class="gradient-segment"
        :style="{
          left: `${seg.startPct}%`,
          width: `${seg.widthPct}%`,
          backgroundColor: seg.color,
        }"
      />
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  components: { type: Array, required: true }, // [{ palette: { hex_code }, weight, position }, ...]
  blendType: { type: String, default: 'piano' },
  size: { type: String, default: 'medium' },
})

const segments = computed(() => {
  const comps = [...props.components].sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0))
  const totalWeight = comps.reduce((sum, c) => sum + (c.weight || 0), 0)
  let acc = 0
  return comps.map((c) => {
    const weight = totalWeight > 0 ? (c.weight || 0) / totalWeight : 1 / comps.length
    const start = acc
    acc += weight
    return {
      color: c.palette?.hex_code || c.hex || '#ccc',
      weight: c.weight || 0.5,
      startPct: start * 100,
      widthPct: weight * 100,
    }
  })
})

const barStyle = computed(() => {
  if (props.blendType !== 'piano') {
    // 线性渐变：用 CSS linear-gradient
    const stops = segments.value.map((s) => `${s.color} ${s.startPct}%, ${s.color} ${s.startPct + s.widthPct}%`)
    return {
      background: `linear-gradient(to right, ${stops.join(', ')})`,
    }
  }
  return {}
})
</script>

<style scoped>
.gradient-bar {
  width: 100%;
  height: 100%;
  position: relative;
  overflow: hidden;
}
.gradient-bar.type-piano {
  display: flex;
}
.piano-segment {
  height: 100%;
}
.gradient-segment {
  position: absolute;
  top: 0;
  bottom: 0;
}
</style>
