<template>
  <el-tag v-bind="$attrs" :type="tone" :effect="effect" class="status-badge">
    <slot>{{ text }}</slot>
  </el-tag>
</template>

<script setup>
import { computed } from 'vue'
import { resolveStatus } from '../utils/status'
defineOptions({ inheritAttrs: false })
const props = defineProps({
  value: { default: undefined },
  dictionary: { type: Object, default: undefined },
  label: { type: [String, Number], default: undefined },
  type: { type: String, default: 'info' },
  effect: { type: String, default: 'plain' },
})
const status = computed(() => {
  const resolved = props.dictionary ? resolveStatus(props.value, props.dictionary) : { label: props.value ?? '未提供', type: props.type }
  return { ...resolved, label: props.label ?? resolved.label }
})
const tone = computed(() => ['primary', 'success', 'warning', 'danger', 'info'].includes(status.value.type) ? status.value.type : 'info')
const text = computed(() => status.value.label)
</script>

<style scoped>
.status-badge { border-radius: 999px; max-width: 100%; height: auto; min-height: 22px; white-space: normal; overflow-wrap: anywhere; line-height: 1.5; padding: 2px 8px; }
</style>
