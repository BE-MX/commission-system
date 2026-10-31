<template>
  <div class="mp">
    <h4>色差仪</h4>
    <ol class="steps" aria-label="连接状态">
      <li v-for="(s, i) in STEPS" :key="s" :class="stepClass(i + 1)">{{ s }}</li>
    </ol>

    <el-alert v-if="!simulate && !meter.support.ok" type="warning" :closable="false" show-icon :title="meter.support.reason" class="mp-alert" />
    <el-alert v-if="d.initWarning" type="warning" :closable="false" show-icon :title="d.initWarning" class="mp-alert" />
    <el-alert v-if="d.error" type="error" :closable="false" show-icon :title="d.error" class="mp-alert" />

    <div class="mp-mode" role="radiogroup" aria-label="设备模式">
      <button
        v-for="m in MODES" :key="m.label" type="button" role="radio" :aria-checked="simulate === m.value"
        :class="{ on: simulate === m.value }" :disabled="connected || d.connecting" @click="simulate = m.value"
      >{{ m.label }}</button>
    </div>

    <dl v-if="connected" class="mp-info">
      <dt>设备</dt><dd>{{ d.name || '—' }}<span v-if="d.simulated" class="mp-sim">模拟</span></dd>
      <dt>SN</dt><dd>{{ d.sn || '—' }}</dd>
      <dt>版本</dt><dd>{{ d.fw ? `v${d.fw}` : '—' }}</dd>
      <dt>电压</dt><dd>{{ d.voltage ? `${d.voltage.toFixed(1)} V` : '—' }}</dd>
      <dt>通道</dt><dd>{{ d.profile ? `配置 ${d.profile}` : '—' }}</dd>
    </dl>

    <el-button class="mp-conn" :loading="d.connecting" :disabled="!connected && !simulate && !meter.support.ok" @click="toggle">
      {{ connected ? '断开' : '连接色差仪' }}
    </el-button>

    <div class="mp-tag">
      <span class="mp-tag-head">
        <span>测量位置 <em class="mp-req">*</em></span>
        <router-link v-any-permission="['dict:write']" :to="{ name: 'DictManagement', query: { type: TAG_TYPE } }" class="mp-tag-manage">维护标签</router-link>
      </span>
      <el-select v-model="tag" placeholder="请选择测量位置" :disabled="d.measuring" class="mp-tag-sel">
        <el-option v-for="t in tags" :key="t.code" :label="t.label" :value="t.code" />
      </el-select>
      <small v-if="!tag" class="mp-tag-tip">{{ tags.length ? '先选择测量位置才能测量' : '暂无可用标签，请先在字典中维护' }}</small>
    </div>

    <button type="button" class="mp-measure" :class="{ busy: d.measuring }" :disabled="!canMeasure" @click="$emit('measure', { count: repeat, tag })">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true">
        <circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="3" />
      </svg>
      <span>{{ d.measuring ? (d.progress ? `测量中 ${d.progress}` : '测量中…') : measureLabel }}</span>
    </button>
    <p class="mp-guide">测量说明：统一沿发丝方向、同样的厚度和白色衬底进行测量。</p>
    <div class="mp-rep">
      连续测量
      <el-input-number v-model="repeat" :min="1" :max="10" controls-position="right" :disabled="d.measuring" class="mp-rep-input" />
      组，每组移动测量位置
    </div>
    <p v-if="!writable" class="mp-hint">当前色板只读，无法写入测量。</p>

    <details class="mp-log">
      <summary>通信日志（{{ d.logs.length }}）</summary>
      <pre>{{ d.logs.join('\n') || '暂无' }}</pre>
    </details>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { getDictItems } from '@/api/system'

const props = defineProps({
  meter: { type: Object, required: true },
  writable: Boolean,
  // Which tab the reading will be filed under; shown on the button so the target is never ambiguous.
  recordType: { type: String, default: 'standard' },
})
defineEmits(['measure'])

const TAG_TYPE = 'color_measure_tag'
const STEPS = ['GATT', '通知', '初始化', '可测量']
const MODES = [{ label: '蓝牙真机', value: false }, { label: '模拟设备', value: true }]
const d = props.meter.device
const simulate = ref(!props.meter.support.ok)
const repeat = ref(3)
const tags = ref([])
const tag = ref('')

const connected = computed(() => d.state > props.meter.STATE.IDLE)
const canMeasure = computed(() => props.writable && !!tag.value && d.state >= props.meter.STATE.NOTIFY && !d.measuring)
const measureLabel = computed(() => (props.recordType === 'batch' ? '测量 · 批次产品' : '测量 · 标准色板'))

onMounted(async () => {
  try {
    tags.value = (await getDictItems(TAG_TYPE, true, { suppressToast: true })).data || []
  } catch (err) {
    console.warn('[swatch-library] load measure tags failed', err)
  }
})

// Map device state onto 4 visible steps: READY lights both 初始化 and 可测量.
function stepClass(step) {
  const reached = d.state >= props.meter.STATE.READY ? 4 : d.state
  if (reached >= step) return 'done'
  if (d.connecting && reached + 1 === step) return 'cur'
  return ''
}

async function toggle() {
  if (connected.value) {
    props.meter.disconnect()
    return
  }
  try {
    await props.meter.connect({ simulate: simulate.value })
  } catch (err) {
    console.warn('[swatch-library] connect failed', err)
  }
}
</script>

<style scoped>
.mp h4 { margin: 0 0 10px; font: 700 14px var(--font-display); color: var(--text-primary); }
.steps { display: flex; gap: 4px; list-style: none; margin: 0 0 12px; padding: 0; }
.steps li {
  flex: 1; text-align: center; padding-top: 8px; border-top: 3px solid var(--border-color);
  font: 600 11px var(--font-display); color: var(--text-muted);
  transition: border-color 200ms ease, color 200ms ease;
}
.steps li.done { border-color: var(--button-success); color: var(--button-success-text); }
.steps li.cur { border-color: var(--button-primary); color: var(--button-warning-text); }
.mp-alert { margin-bottom: 10px; }
.mp-mode { display: flex; gap: 6px; margin-bottom: 12px; }
.mp-mode button {
  flex: 1; height: 32px; border: 1px solid var(--border-color); border-radius: var(--radius-md, 8px); cursor: pointer;
  background: var(--card-bg); font: 600 12px var(--font-display); color: var(--text-secondary);
  transition: border-color 160ms ease, background-color 160ms ease, color 160ms ease, transform 120ms ease-out;
}
.mp-mode button:active:not(:disabled) { transform: scale(0.97); }
.mp-mode button.on { border-color: var(--color-primary); background: var(--color-primary-light); color: var(--button-primary-text); }
.mp-mode button:disabled { cursor: not-allowed; opacity: 0.6; }
.mp-mode button:focus-visible { outline: 2px solid var(--button-focus); outline-offset: 1px; }
.mp-info { display: grid; grid-template-columns: auto 1fr; gap: 6px 12px; margin: 0 0 12px; font-size: 12.5px; }
.mp-info dt { color: var(--text-muted); }
.mp-info dd { margin: 0; font-weight: 600; color: var(--text-primary); font-variant-numeric: tabular-nums; }
.mp-sim { margin-left: 6px; padding: 0 5px; border-radius: 4px; font-size: 10px; background: var(--tag-info-bg); color: var(--color-info-text); }
.mp-conn { width: 100%; margin-bottom: 10px; }
.mp-tag { display: grid; gap: 6px; margin-bottom: 10px; }
.mp-tag-head { display: flex; justify-content: space-between; font: 600 12px var(--font-display); color: var(--text-secondary); }
.mp-tag-manage { font-weight: 500; color: var(--button-primary-text); text-decoration: none; }
.mp-tag-sel { width: 100%; }
.mp-req { font-style: normal; color: var(--tag-danger-text); }
.mp-tag-tip { font-size: 11.5px; color: var(--text-muted); }
.mp-measure {
  position: relative; overflow: hidden; width: 100%; height: 52px; border: 0; border-radius: var(--card-radius);
  display: flex; align-items: center; justify-content: center; gap: 8px; cursor: pointer;
  font: 700 15px var(--font-display); background: var(--button-primary); color: var(--button-primary-ink);
  transition: background-color 160ms ease, transform 120ms ease-out;
}
.mp-measure:active:not(:disabled) { transform: scale(0.97); }
.mp-measure:focus-visible { outline: 2px solid var(--button-focus); outline-offset: 2px; }
.mp-measure:disabled { background: var(--button-disabled-bg); color: var(--button-disabled-text); cursor: not-allowed; }
@media (hover: hover) and (pointer: fine) { .mp-measure:hover:not(:disabled) { background: var(--button-primary-hover); } }
/* Indeterminate progress sheen while waiting for the 44 frame: constant motion → linear. */
.mp-measure.busy::before {
  content: ''; position: absolute; inset: 0;
  background: linear-gradient(90deg, transparent, rgb(255 255 255 / 0.45), transparent);
  animation: mp-sweep 1s linear infinite;
}
@keyframes mp-sweep { from { transform: translateX(-100%); } to { transform: translateX(100%); } }
@media (prefers-reduced-motion: reduce) { .mp-measure.busy::before { animation: none; opacity: 0.35; } }
.mp-guide {
  margin: 8px 0 0; padding: 7px 10px; border-radius: var(--radius-md, 8px); font-size: 12px; line-height: 1.6;
  background: var(--tag-info-bg); color: var(--color-info-text);
}
.mp-rep { display: flex; align-items: center; gap: 8px; margin-top: 10px; font-size: 12.5px; color: var(--text-secondary); flex-wrap: wrap; }
.mp-rep-input { width: 100px; }
.mp-hint { margin: 8px 0 0; font-size: 12px; color: var(--text-muted); }
.mp-log { margin-top: 12px; font-size: 12px; color: var(--text-secondary); }
.mp-log summary { cursor: pointer; }
.mp-log pre {
  margin: 6px 0 0; max-height: 140px; overflow: auto; padding: 8px 10px; white-space: pre-wrap; word-break: break-all;
  font: 11px/1.6 var(--font-mono); color: var(--text-tertiary); background: var(--page-bg);
  border: 1px solid var(--border-color); border-radius: var(--radius-md, 8px);
}
</style>
