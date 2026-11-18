<template>
  <div ref="stage" class="scan-corners" :style="stageStyle">
    <img :src="src" alt="待裁剪的文档照片" draggable="false" />
    <svg viewBox="0 0 1 1" preserveAspectRatio="none" class="corner-lines" aria-hidden="true">
      <polygon :points="polygon" vector-effect="non-scaling-stroke" />
    </svg>
    <button
      v-for="([x, y], index) in modelValue"
      :key="index"
      type="button"
      class="corner-handle"
      :style="{ left: x * 100 + '%', top: y * 100 + '%' }"
      :aria-label="labels[index]"
      @pointerdown="startDrag($event, index)"
      @pointermove="moveDrag"
      @pointerup="endDrag"
      @pointercancel="endDrag"
      @lostpointercapture="endDrag"
      @keydown="moveWithKey($event, index)"
    ><span></span></button>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { isValidQuad } from './documentQuad'

const props = defineProps({
  modelValue: { type: Array, required: true },
  src: { type: String, required: true },
  ratio: { type: Number, required: true },
})
const emit = defineEmits(['update:modelValue'])
const stage = ref(null)
const labels = ['左上角', '右上角', '右下角', '左下角']
const polygon = computed(() => props.modelValue.map(point => point.join(',')).join(' '))
const stageStyle = computed(() => ({
  aspectRatio: props.ratio,
  width: 'min(100%, ' + (props.ratio * 51) + 'svh, 680px)',
}))
let drag = null

function moveCorner(index, x, y) {
  const points = props.modelValue.slice()
  points[index] = [Math.min(1, Math.max(0, x)), Math.min(1, Math.max(0, y))]
  if (isValidQuad(points)) emit('update:modelValue', points)
}

function startDrag(event, index) {
  if (drag || !event.isPrimary || event.button !== 0) return
  const bounds = stage.value.getBoundingClientRect()
  drag = {
    id: event.pointerId,
    index,
    offsetX: props.modelValue[index][0] * bounds.width - (event.clientX - bounds.left),
    offsetY: props.modelValue[index][1] * bounds.height - (event.clientY - bounds.top),
  }
  event.currentTarget.setPointerCapture(event.pointerId)
}

function moveDrag(event) {
  if (drag?.id !== event.pointerId) return
  const bounds = stage.value.getBoundingClientRect()
  moveCorner(
    drag.index,
    (event.clientX - bounds.left + drag.offsetX) / bounds.width,
    (event.clientY - bounds.top + drag.offsetY) / bounds.height,
  )
}

function endDrag(event) {
  if (drag?.id === event.pointerId) drag = null
}

function moveWithKey(event, index) {
  const directions = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }
  if (!Object.hasOwn(directions, event.key)) return
  event.preventDefault()
  const [dx, dy] = directions[event.key]
  const step = event.shiftKey ? 0.025 : 0.005
  const [x, y] = props.modelValue[index]
  moveCorner(index, x + dx * step, y + dy * step)
}
</script>

<style scoped>
.scan-corners {
  position: relative;
  margin: 0 auto;
}
.scan-corners img {
  display: block;
  width: 100%;
  height: 100%;
  user-select: none;
  border-radius: var(--el-border-radius-base);
}
.corner-lines {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  overflow: visible;
  pointer-events: none;
}
.corner-lines polygon {
  fill: var(--button-primary);
  fill-opacity: 0.06;
  stroke: var(--button-primary);
  stroke-width: 2px;
}
.corner-handle {
  position: absolute;
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  padding: 0;
  transform: translate(-50%, -50%);
  border: 0;
  border-radius: 50%;
  background: transparent;
  touch-action: none;
  cursor: grab;
  -webkit-tap-highlight-color: transparent;
}
.corner-handle:active { cursor: grabbing; }
.corner-handle:focus-visible { outline: 2px solid var(--button-primary); }
.corner-handle span {
  width: 18px;
  height: 18px;
  border: 2px solid var(--button-primary-text);
  border-radius: 50%;
  background: var(--button-primary);
  box-shadow: var(--el-box-shadow-light);
  pointer-events: none;
}
</style>
