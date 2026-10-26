<template>
  <div class="pg-card">
    <div class="pg-card-title"><h2>投递台账</h2><span class="pg-note">每期每接收人一行；支持预览与补发</span></div>
    <div class="pg-filter-bar">
      <label>期次</label>
      <el-input v-model="slotFilter" clearable placeholder="如 2026-10-20" class="pg-w-150" @change="search" />
      <label>范围</label>
      <el-select v-model="scopeFilter" clearable placeholder="全部" class="pg-w-130" @change="search">
        <el-option label="业务员" value="person" />
        <el-option label="组长/战队" value="team" />
        <el-option label="管理层/整体" value="company" />
      </el-select>
      <span class="pg-sum">共 <b>{{ total }}</b> 条投递记录</span>
    </div>
    <div class="pg-table-wrap" v-loading="loading">
      <table class="pg-tbl">
        <thead>
          <tr>
            <th>期次</th><th>报告类型</th><th>接收人</th><th>战队</th><th>生成时间</th><th>状态</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.id">
            <td>{{ r.slot }}</td>
            <td>{{ scopeLabel(r.scope) }}</td>
            <td>{{ r.user_name || '—' }}</td>
            <td>{{ r.team_name || '—' }}</td>
            <td>{{ r.created_at ? formatBeijingDateTime(r.created_at) : '—' }}</td>
            <td><span class="pg-tag" :class="statusClass(r.status)">{{ statusText(r.status) }}</span></td>
            <td>
              <el-button @click="$emit('preview', r)">预览</el-button>
              <el-button :loading="resending === r.id" @click="resend(r)">补发</el-button>
            </td>
          </tr>
          <tr v-if="!rows.length && !loading"><td colspan="7" class="pg-empty">暂无投递记录</td></tr>
        </tbody>
      </table>
    </div>
    <div class="pg-pager">
      <span>每页 {{ pageSize }} 条 · 共 {{ total }} 条</span>
      <button :disabled="page <= 1" @click="changePage(page - 1)">‹</button>
      <button :disabled="page >= pages" @click="changePage(page + 1)">›</button>
    </div>
    <div class="pg-footnote">状态机：pending → sending → sent / failed（自动重试）→ uncertain；未绑定钉钉ID 的接收人自动降级为战报群 @ 并标记 degraded。</div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { msgSuccessText } from '@/utils/feedback'
import { perfGoalApi } from '@/api/perfGoal'
import { formatBeijingDateTime } from '@/utils/datetime'

defineEmits(['preview'])

const rows = ref([]), total = ref(0), loading = ref(false)
const page = ref(1), pageSize = 15
const slotFilter = ref(''), scopeFilter = ref('')
const resending = ref(null)

const pages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
const scopeLabel = s => ({ person: '业务员报告', team: '组长报告', company: '管理层报告' }[s] || s || '—')
const statusText = s => ({ sent: '已送达', failed: '失败', pending: '待发送', sending: '发送中', degraded: '降级群@', uncertain: '状态未知' }[s] || s || '—')
const statusClass = s => ({ sent: 'pg-green', degraded: 'pg-amber', failed: 'pg-orange', uncertain: 'pg-orange' }[s] || 'pg-gray')

async function load() {
  loading.value = true
  try {
    const res = await perfGoalApi.reports({
      slot: slotFilter.value || undefined,
      scope: scopeFilter.value || undefined,
      page: page.value,
      page_size: pageSize,
    }, { suppressToast: true })
    rows.value = res.rows || []
    total.value = res.total ?? rows.value.length
  } catch {
    rows.value = []; total.value = 0
  } finally {
    loading.value = false
  }
}
function search() { page.value = 1; load() }
function changePage(p) { if (p >= 1 && p <= pages.value) { page.value = p; load() } }
async function resend(r) {
  resending.value = r.id
  try {
    await perfGoalApi.resendReport(r.id)
    msgSuccessText(`已向 ${r.user_name || r.team_name || '接收人'} 重新推送`)
    await load()
  } finally {
    resending.value = null
  }
}
onMounted(load)
defineExpose({ reload: load })
</script>
