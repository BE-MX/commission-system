<template>
  <div :class="['pace-widget', { ahead: row.ahead_of_time === true, behind: row.ahead_of_time === false }]">
    <div class="pace-track" role="progressbar" :aria-valuenow="row.progress_percent ?? 0" aria-valuemin="0" :aria-valuemax="Math.max(100, row.progress_percent || 0)" :aria-label="description">
      <i class="pace-fill" :style="{ width: `${Math.max(0, Math.min(100, row.progress_percent || 0))}%` }" />
      <i v-if="time" class="pace-marker" :style="{ left: `clamp(1px, ${time.percent}%, calc(100% - 1px))` }" />
    </div>
    <div v-if="time" class="pace-caption"><span>{{ row.ahead_of_time == null ? '待补全' : row.ahead_of_time ? '跑赢时间' : '未跑赢时间' }}</span><span>时间 {{ time.percent.toFixed(2) }}%</span></div>
  </div>
</template>
<script setup>
import { computed } from 'vue'
const props = defineProps({ row: { type: Object, required: true }, time: { type: Object, default: null } })
const description = computed(() => `完成 ${props.row.progress_percent ?? '待补全'}%，${props.time ? `工作日进度 ${props.time.percent}%，${props.row.ahead_of_time ? '跑赢时间' : '未跑赢时间'}` : '尚未配置工作日'}`)
</script>
<style scoped>
.pace-track{height:8px;position:relative;background:var(--color-primary-light);border-radius:4px;overflow:hidden;margin:6px 0}.pace-fill{display:block;height:100%;background:var(--color-primary);border-radius:4px}.ahead .pace-fill{background:var(--color-success)}.behind .pace-fill{background:var(--color-danger)}.ahead .pace-track{background:var(--color-success-bg)}.behind .pace-track{background:var(--color-danger-bg)}.pace-marker{position:absolute;top:0;bottom:0;width:2px;background:var(--text-primary);transform:translateX(-50%)}.pace-caption{display:flex;justify-content:space-between;gap:8px;font-size:11px;color:var(--text-secondary);flex-wrap:wrap}.ahead .pace-caption>span:first-child{color:var(--color-success-text)}.behind .pace-caption>span:first-child{color:var(--color-danger)}
</style>
