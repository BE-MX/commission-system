<template>
  <el-tag v-bind="$attrs" :type="tone" :effect="effect" class="status-badge">
    <span ref="labelElement" class="status-badge__label" :title="$attrs.title === undefined ? labelTitle : $attrs.title"><slot>{{ text }}</slot></span>
  </el-tag>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, onUpdated, ref } from 'vue'
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
const labelElement = ref(null)
const labelTitle = ref('')
let labelObserver
function syncLabelTitle() {
  const rendered = labelElement.value?.textContent
  labelTitle.value = typeof rendered === 'string' ? rendered.replace(/\s+/g, ' ').trim() : String(text.value ?? '')
}
onMounted(() => {
  syncLabelTitle()
  // Slot descendants can update inside ElTag without updating this component.
  if (typeof MutationObserver !== 'undefined' && labelElement.value) {
    labelObserver = new MutationObserver(syncLabelTitle)
    labelObserver.observe(labelElement.value, { childList: true, characterData: true, subtree: true })
  }
})
onUpdated(syncLabelTitle)
onBeforeUnmount(() => labelObserver?.disconnect())
</script>

<style scoped>
.status-badge {
  display: inline-block;
  border-radius: 999px;
  max-width: 100%;
  height: auto;
  min-height: 22px;
  white-space: nowrap;
  line-height: 1.5;
  padding: 2px 8px;
}
.status-badge__label {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: top;
}
.status-badge.is-closable .status-badge__label {
  max-width: calc(100% - var(--el-icon-size) - 6px);
}
</style>
