<!--
  Apple 风格分段控件：共享滑动底板（纯 transform/width 过渡，可中途打断），
  统一窗口切换与视角切换的节奏与手感。
-->
<template>
  <div
    ref="trackRef"
    class="seg-control"
    :class="[`seg-control--${size}`, { 'is-ready': ready }]"
    role="radiogroup"
    :aria-label="ariaLabel"
  >
    <span
      v-if="thumb.width > 0"
      class="seg-thumb"
      aria-hidden="true"
      :style="{ width: `${thumb.width}px`, transform: `translate3d(${thumb.x}px, 0, 0)` }"
    />
    <button
      v-for="(opt, idx) in options"
      :key="opt.value"
      :ref="el => setBtnRef(el, idx)"
      type="button"
      role="radio"
      class="seg-item"
      :class="{ 'is-active': opt.value === modelValue }"
      :aria-checked="opt.value === modelValue"
      :disabled="disabled"
      @click="select(opt.value)"
      @keydown.left.prevent="step(-1)"
      @keydown.right.prevent="step(1)"
    >
      {{ opt.label }}
    </button>
  </div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

const props = defineProps({
  modelValue: { type: [String, Number], required: true },
  options: { type: Array, required: true },
  size: { type: String, default: 'md' },
  disabled: { type: Boolean, default: false },
  ariaLabel: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue', 'change'])

const trackRef = ref(null)
const btnRefs = []
const ready = ref(false)
const thumb = reactive({ x: 0, width: 0 })
let observer = null

function setBtnRef(el, idx) {
  if (el) btnRefs[idx] = el
}

function measure() {
  const idx = props.options.findIndex(opt => opt.value === props.modelValue)
  const btn = btnRefs[idx]
  if (!btn || !trackRef.value) return
  thumb.x = btn.offsetLeft
  thumb.width = btn.offsetWidth
}

function select(value) {
  if (props.disabled || value === props.modelValue) return
  emit('update:modelValue', value)
  emit('change', value)
}

function step(delta) {
  if (props.disabled || !props.options.length) return
  const idx = props.options.findIndex(opt => opt.value === props.modelValue)
  const next = (idx + delta + props.options.length) % props.options.length
  const target = props.options[next]
  select(target.value)
  btnRefs[next]?.focus()
}

watch(() => [props.modelValue, props.options.length], async () => {
  await nextTick()
  measure()
})

onMounted(async () => {
  await nextTick()
  measure()
  requestAnimationFrame(() => { ready.value = true })
  if (typeof ResizeObserver !== 'undefined' && trackRef.value) {
    observer = new ResizeObserver(measure)
    observer.observe(trackRef.value)
  }
})

onBeforeUnmount(() => observer?.disconnect())
</script>

<style scoped>
.seg-control {
  position: relative;
  display: inline-flex;
  align-items: center;
  padding: 3px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: var(--toolbar-bg);
  user-select: none;
  max-width: 100%;
  overflow-x: auto;
  scrollbar-width: none;
}
.seg-control::-webkit-scrollbar { display: none; }

.seg-thumb {
  position: absolute;
  top: 3px;
  bottom: 3px;
  left: 0;
  border-radius: 7px;
  background: var(--card-bg);
  box-shadow: 0 1px 3px rgba(26, 24, 22, 0.08), 0 0 0 1px rgba(212, 148, 28, 0.22);
  pointer-events: none;
  z-index: 0;
  will-change: transform, width;
}
.seg-control.is-ready .seg-thumb {
  transition: transform var(--motion-base) var(--ease-in-out-strong), width var(--motion-base) var(--ease-in-out-strong);
}

.seg-item {
  position: relative;
  z-index: 1;
  border: 0;
  background: transparent;
  color: var(--text-secondary);
  font-family: var(--font-display);
  font-weight: 500;
  font-size: 13px;
  line-height: 1;
  height: 30px;
  padding: 0 12px;
  border-radius: 7px;
  white-space: nowrap;
  cursor: pointer;
  transition: color var(--motion-fast) ease, transform var(--motion-press) var(--ease-out-strong);
}
.seg-control--sm .seg-item {
  height: 28px;
  padding: 0 10px;
  font-size: 12px;
}
@media (hover: hover) and (pointer: fine) {
  .seg-item:not(.is-active):not(:disabled):hover {
    color: var(--text-primary);
  }
}
.seg-item:active:not(:disabled) {
  transform: scale(0.97);
}
.seg-item.is-active {
  color: var(--color-primary-text);
  font-weight: 600;
}
.seg-item:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: -2px;
}
.seg-item:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

@media (prefers-reduced-motion: reduce) {
  .seg-control.is-ready .seg-thumb {
    transition: none;
  }
  .seg-item:active:not(:disabled) {
    transform: none;
  }
}
</style>
