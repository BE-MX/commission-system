<template>
  <div class="pill" :title="title">
    <span class="dot" :class="tone" />
    <span class="txt">{{ label }}</span>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  device: { type: Object, required: true },
  stateEnum: { type: Object, required: true },
})

const tone = computed(() => {
  if (props.device.state >= props.stateEnum.READY) return 'ok'
  if (props.device.state > props.stateEnum.IDLE || props.device.connecting) return 'mid'
  return ''
})
const label = computed(() => {
  const d = props.device
  if (d.state >= props.stateEnum.READY) return `${d.name}${d.voltage ? ` · ${d.voltage.toFixed(1)} V` : ''}`
  if (d.state > props.stateEnum.IDLE || d.connecting) return '色差仪连接中…'
  return '色差仪未连接'
})
const title = computed(() => (props.device.simulated ? '当前为模拟设备' : ''))
</script>

<style scoped>
.pill {
  display: inline-flex; align-items: center; gap: 8px; height: 32px; padding: 0 12px; border-radius: 999px;
  border: 1px solid var(--border-color); background: var(--card-bg);
  font: 600 12px var(--font-display); color: var(--text-secondary); max-width: 220px;
}
.txt { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.dot { flex: 0 0 8px; height: 8px; border-radius: 50%; background: var(--button-disabled-text); transition: background-color 200ms ease; }
.dot.ok { background: var(--button-success); box-shadow: 0 0 0 3px var(--button-success-soft); }
.dot.mid { background: var(--button-primary); box-shadow: 0 0 0 3px var(--button-primary-soft); }
</style>
