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
            <td>{{ a.operator_name || '—' }}</td>
            <td>{{ a.object_label || a.object_type || '—' }}</td>
            <td>{{ changeLabel(a) }}</td>
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
function changeLabel(a) {
  return [a.field, a.reason].filter(Boolean).join(' · ') || '—'
}
function changeText(a) {
  if (a.old_value == null && a.new_value == null) return '—'
  const fmt = v => (typeof v === 'object' ? JSON.stringify(v) : String(v ?? '—'))
  return `${fmt(a.old_value)} → ${fmt(a.new_value)}`
}

async function load() {
  if (!props.periodId) { rows.value = []; return }
  loading.value = true
  try {
    const res = await perfGoalApi.audits(props.periodId, {}, { suppressToast: true })
    rows.value = Array.isArray(res) ? res : (res.rows || res.items || [])
  } catch {
    rows.value = []
  } finally {
    loading.value = false
  }
}
watch(() => props.periodId, load, { immediate: true })
defineExpose({ reload: load })
</script>
