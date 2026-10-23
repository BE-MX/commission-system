<template>
  <div class="pg-card">
    <div class="pg-card-title"><h2>变更留痕</h2><span class="pg-note">目标与战队系数调整记录</span></div>
    <div class="pg-table-wrap" v-loading="loading">
      <table class="pg-tbl">
        <thead>
          <tr><th>时间</th><th>操作人</th><th>对象</th><th>变更内容</th><th>旧值 → 新值</th></tr>
        </thead>
        <tbody>
          <tr v-for="(a, i) in rows" :key="a.id ?? i">
            <td>{{ formatTime(a.created_at) }}</td>
            <td>{{ a.actor_name || a.actor_id || '—' }}</td>
            <td>{{ a.target_label || a.object || '—' }}</td>
            <td>{{ a.action_label || a.action || a.summary || '—' }}</td>
            <td>{{ changeText(a) }}</td>
          </tr>
          <tr v-if="!rows.length && !loading"><td colspan="5" class="pg-empty">暂无变更记录</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { perfGoalApi } from '@/api/perfGoal'
import { formatBeijingDateTime } from '@/utils/datetime'

const props = defineProps({
  periodId: { type: [String, Number], default: null },
})
const rows = ref([]), loading = ref(false)

const formatTime = v => (v ? formatBeijingDateTime(v) : '—')
function changeText(a) {
  if (a.change_text) return a.change_text
  const before = a.before_text ?? a.before
  const after = a.after_text ?? a.after
  if (before == null && after == null) return '—'
  const fmt = v => (typeof v === 'object' ? JSON.stringify(v) : String(v ?? '—'))
  return `${fmt(before)} → ${fmt(after)}`
}

async function load() {
  if (!props.periodId) { rows.value = []; return }
  loading.value = true
  try {
    const res = await perfGoalApi.audits(props.periodId, {}, { suppressToast: true })
    rows.value = res.rows || res.items || []
  } catch {
    rows.value = []
  } finally {
    loading.value = false
  }
}
watch(() => props.periodId, load, { immediate: true })
defineExpose({ reload: load })
</script>
