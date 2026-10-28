<template>
  <div class="mt-wrap">
    <table class="mt">
      <thead>
        <tr v-if="view === 'lab'"><th>组</th><th>时间</th><th>L*</th><th>a*</th><th>b*</th><th>ΔE→均值</th><th>来源</th><th v-if="writable">操作</th></tr>
        <tr v-else-if="view === 'cmyk'"><th>组</th><th>C</th><th>M</th><th>Y</th><th>K</th><th>R</th><th>G</th><th>B</th><th v-if="writable">操作</th></tr>
        <tr v-else><th>组</th><th>Lab</th><th>Luv</th><th>LCh</th><th>Yxy</th><th>设备 SN</th><th v-if="writable">操作</th></tr>
      </thead>
      <tbody>
        <tr v-if="!rows.length">
          <td :colspan="writable ? 9 : 8" class="mt-empty">连接色差仪后点击“测量”，每组读数会自动加入</td>
        </tr>
        <tr v-for="m in rows" :key="m.id" :class="{ excl: !m.is_included, fresh: freshIds.has(m.id) }">
          <td class="first">
            <span class="mini" :style="{ background: m.rgb[0] == null ? 'var(--button-quiet-hover)' : rgbCss(m.rgb) }" />
            #{{ m.seq_no }}
            <span v-if="!m.is_included" class="tag" :title="m.exclude_reason">已剔除</span>
            <span v-if="m.receipt_status === 'late'" class="tag tag-warn">晚到</span>
          </td>
          <template v-if="view === 'lab'">
            <td>{{ formatBeijing(m.received_at || m.created_at) }}</td>
            <td>{{ fmt(m.lab[0]) }}</td><td>{{ fmt(m.lab[1]) }}</td><td>{{ fmt(m.lab[2]) }}</td>
            <td>{{ m.is_included && avgLab ? fmt(de00(m.lab, avgLab)) : '—' }}</td>
            <td>{{ SOURCE[m.source] || m.source }}</td>
          </template>
          <template v-else-if="view === 'cmyk'">
            <td v-for="(v, i) in m.cmyk" :key="`c${i}`">{{ v ?? '—' }}</td>
            <td v-for="(v, i) in m.rgb" :key="`r${i}`">{{ v ?? '—' }}</td>
          </template>
          <template v-else>
            <td>{{ triple(m.lab) }}</td><td>{{ triple(m.luv) }}</td><td>{{ triple(m.lch) }}</td>
            <td>{{ m.yxy[0] == null ? '—' : `${fmt(m.yxy[0])} / ${fmt(m.yxy[1], 4)} / ${fmt(m.yxy[2], 4)}` }}</td>
            <td>{{ m.device_sn || '—' }}</td>
          </template>
          <td v-if="writable" class="op">
            <el-button link :type="m.is_included ? 'danger' : 'primary'" @click="$emit('toggle', m)">
              {{ m.is_included ? '剔除' : '恢复' }}
            </el-button>
          </td>
        </tr>
      </tbody>
      <tfoot v-if="avgLab">
        <tr v-if="view === 'lab'">
          <td class="first">平均</td><td />
          <td>{{ fmt(avgLab[0]) }}</td><td>{{ fmt(avgLab[1]) }}</td><td>{{ fmt(avgLab[2]) }}</td>
          <td>{{ fmt(meanDE) }}</td><td /><td v-if="writable" />
        </tr>
        <tr v-else-if="view === 'cmyk'">
          <td class="first">平均 <span class="tag">设备换算值</span></td>
          <td v-for="(v, i) in avgBytes.cmyk" :key="`ac${i}`">{{ v ?? '—' }}</td>
          <td v-for="(v, i) in avgBytes.rgb" :key="`ar${i}`">{{ v ?? '—' }}</td>
          <td v-if="writable" />
        </tr>
      </tfoot>
    </table>
    <p v-if="view === 'cmyk' && rows.length" class="mt-note">CMYK / RGB 为设备返回的换算值，仅用于预览，不参与色差判定。</p>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { de00, rgbCss } from '@/services/colorimeter/deltaE.js'
import { fmt, formatBeijing } from './swatchFormat.js'

const props = defineProps({
  measurements: { type: Array, default: () => [] },
  avgLab: { type: Array, default: null },
  view: { type: String, default: 'lab' },
  writable: Boolean,
  freshIds: { type: Set, default: () => new Set() },
})
defineEmits(['toggle'])

const SOURCE = { device: '色差仪', simulation: '模拟', manual: '手工' }
const rows = computed(() => [...props.measurements].reverse())
const included = computed(() => props.measurements.filter((m) => m.is_included))
const meanDE = computed(() => {
  if (!props.avgLab || included.value.length < 2) return null
  return included.value.reduce((s, m) => s + de00(m.lab, props.avgLab), 0) / included.value.length
})
const avgBytes = computed(() => {
  const avg = (key, n) => Array.from({ length: n }, (_, i) => {
    const vals = included.value.map((m) => m[key][i]).filter((v) => v != null)
    return vals.length ? Math.round(vals.reduce((a, b) => a + b, 0) / vals.length) : null
  })
  return { cmyk: avg('cmyk', 4), rgb: avg('rgb', 3) }
})
const triple = (t) => (t?.[0] == null ? '—' : t.map((v) => fmt(v)).join(' / '))
</script>

<style scoped>
.mt-wrap { overflow-x: auto; margin: 0 -18px; }
.mt { width: 100%; min-width: 680px; border-collapse: collapse; font-size: 13px; }
.mt th {
  background: var(--page-bg); font: 600 12.5px var(--font-display); color: var(--text-secondary);
  text-align: right; padding: 9px 10px; border-bottom: 1px solid var(--border-color); white-space: nowrap;
}
.mt td { padding: 9px 10px; border-bottom: 1px solid var(--border-color); text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
.mt th:first-child, .mt td.first { text-align: left; padding-left: 18px; }
.mt th:last-child, .mt td:last-child { padding-right: 18px; }
.mt tbody tr { transition: background-color 160ms ease; }
@media (hover: hover) and (pointer: fine) { .mt tbody tr:hover { background: var(--color-primary-light); } }
.mt tr.excl td:not(.first):not(.op) { color: var(--text-muted); text-decoration: line-through; }
/* New readings fade from a gold wash; occasional event (per measurement), so a short highlight is fine. */
.mt tr.fresh { animation: mt-fresh 1.2s cubic-bezier(0.23, 1, 0.32, 1); }
@keyframes mt-fresh { from { background: var(--color-gold-soft); } to { background: transparent; } }
@media (prefers-reduced-motion: reduce) { .mt tr.fresh { animation: none; } }
.mt tfoot td { font-weight: 600; background: var(--page-bg); }
.mt-empty { text-align: center !important; color: var(--text-muted); padding: 28px 0 !important; }
.mini { display: inline-block; width: 14px; height: 14px; border-radius: 4px; vertical-align: -2px; margin-right: 6px; box-shadow: inset 0 0 0 1px rgb(0 0 0 / 0.1); }
.tag { display: inline-flex; align-items: center; height: 18px; padding: 0 6px; margin-left: 4px; border-radius: 5px; font: 600 10.5px var(--font-display); background: var(--button-quiet-hover); color: var(--text-secondary); text-decoration: none; }
.tag-warn { background: var(--tag-warning-bg); color: var(--tag-warning-text); }
.mt-note { margin: 10px 0 0; font-size: 12px; color: var(--text-muted); }
</style>
