<template>
  <el-tooltip
    :content="text"
    :disabled="!overflowing"
    :visible="tooltipVisible"
    placement="top"
    :show-after="300"
  >
    <span
      ref="textElement"
      class="overflow-tooltip"
      :tabindex="focusable && overflowing ? 0 : undefined"
      @mouseenter="hovering = true"
      @mouseleave="hovering = false"
      @focus="handleFocus"
      @blur="handleBlur"
    >{{ text }}</span>
  </el-tooltip>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { isTextOverflowing, overflowTooltipVisible } from '../knowledgeUi.js'

const props = defineProps({
  text: { type: String, required: true },
  focusable: { type: Boolean, default: true },
})

const textElement = ref(null)
const overflowing = ref(false)
const hovering = ref(false)
const focused = ref(false)
const tooltipVisible = computed(() => overflowTooltipVisible({
  overflowing: overflowing.value,
  hovering: hovering.value,
  focused: props.focusable && focused.value,
}))
let resizeObserver

function handleFocus() {
  if (props.focusable) focused.value = true
}

function handleBlur() {
  focused.value = false
}

const measure = () => {
  const element = textElement.value
  overflowing.value = isTextOverflowing(element)
}

onMounted(() => {
  resizeObserver = new ResizeObserver(measure)
  const element = textElement.value
  if (element) resizeObserver.observe(element)
  measure()
})

watch(() => props.text, () => nextTick(measure))

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
})
</script>

<style scoped>
.overflow-tooltip {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (prefers-reduced-motion: reduce) {
  .overflow-tooltip {
    transition: none;
  }
}
</style>

