<template>
  <svg class="scan-frame" :class="{ found: !!corners, aligned }" viewBox="0 0 1 1" preserveAspectRatio="none" aria-hidden="true">
    <path class="dim" :d="`M0 0H1V1H0Z ${quadPath}`" fill-rule="evenodd" />
    <polygon class="edge" :points="points" vector-effect="non-scaling-stroke" />
    <path class="brackets" :d="bracketPath" vector-effect="non-scaling-stroke" />
  </svg>
</template>

<script setup>
// 动态取景框：显示的四角每帧向检测结果滑动（指数逼近），检测丢失时滑回引导框。
// 检测约 135ms 一次，靠插值让框看起来连续跟随纸张，而不是一跳一跳。
import { computed, onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps({
  corners: { type: Array, default: null },
  aligned: { type: Boolean, default: false },
  guide: { type: Array, default: () => [[0.17, 0.13], [0.83, 0.13], [0.83, 0.76], [0.17, 0.76]] },
})

const TAU = 70
const reduceMotion = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
const shown = ref(props.guide.map(point => [...point]))
let frame = 0
let last = 0

function tick(now) {
  const target = props.corners || props.guide
  const k = reduceMotion ? 1 : 1 - Math.exp(-Math.min(now - (last || now), 64) / TAU)
  last = now
  let moving = false
  shown.value = shown.value.map(([x, y], i) => {
    const [tx, ty] = target[i]
    const nx = x + (tx - x) * k, ny = y + (ty - y) * k
    if (Math.abs(tx - nx) + Math.abs(ty - ny) > 0.0005) moving = true
    return [nx, ny]
  })
  frame = moving ? requestAnimationFrame(tick) : 0
  if (!moving) { shown.value = target.map(point => [...point]); last = 0 }
}

function animate() { if (!frame) frame = requestAnimationFrame(tick) }
watch(() => props.corners, animate, { deep: true })
onBeforeUnmount(() => cancelAnimationFrame(frame))

const points = computed(() => shown.value.map(point => point.join(',')).join(' '))
const quadPath = computed(() => `M${shown.value.map(point => point.join(' ')).join('L')}Z`)
// 四角各画一段 L 形：沿相邻两条边取 18% 长度
const bracketPath = computed(() => shown.value.map((point, i, all) => {
  const prev = all[(i + 3) % 4], next = all[(i + 1) % 4]
  const along = (to) => [point[0] + (to[0] - point[0]) * 0.18, point[1] + (to[1] - point[1]) * 0.18]
  const a = along(prev), b = along(next)
  return `M${a.join(' ')}L${point.join(' ')}L${b.join(' ')}`
}).join(''))
</script>

<style scoped>
.scan-frame { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; overflow: visible; }
.dim { fill: var(--camera-scrim); stroke: none; opacity: 0; transition: opacity var(--motion-fast) var(--ease-out-strong); }
.edge { fill: var(--button-primary); fill-opacity: 0; stroke: var(--button-primary); stroke-width: 1.5px; stroke-opacity: 0; transition: fill-opacity var(--motion-fast) var(--ease-out-strong), stroke-opacity var(--motion-fast) var(--ease-out-strong); }
.brackets { fill: none; stroke: var(--camera-ink); stroke-width: 3px; stroke-linecap: round; stroke-linejoin: round; opacity: 0.85; transition: stroke var(--motion-fast) ease; }
.found .dim { opacity: 1; }
.found .edge { fill-opacity: 0.1; stroke-opacity: 0.9; }
.found .brackets { stroke: var(--button-primary); }
.aligned .edge { fill-opacity: 0.18; stroke-width: 2.5px; stroke-opacity: 1; }
@media (prefers-reduced-motion: reduce) {
  .dim, .edge, .brackets { transition-duration: 120ms; }
}
</style>
