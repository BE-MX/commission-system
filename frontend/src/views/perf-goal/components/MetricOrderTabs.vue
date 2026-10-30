<template>
  <div class="pg-card">
    <div class="pg-card-title">
      <h2>指标明细</h2>
      <span class="pg-note">默认沿用当前分析范围；可在此调整明细条件</span>
    </div>
    <p class="pg-context-note">{{ detailsAdjusted ? '已调整明细范围' : analysisLabel }}{{ detailsAdjusted && filters.listedOnly ? ' · 有年度目标人员' : '' }} · {{ filters.range?.join(' 至 ') || '请选择日期' }} <GlassButton v-if="detailsAdjusted" variant="link" @click="applyDefaults">恢复当前分析条件</GlassButton></p>
    <div class="pg-detail-tabs" role="group" aria-label="明细指标">
      <button v-for="t in tabs" :key="t.key" :aria-pressed="tab === t.key" :class="{ 'pg-active': tab === t.key }" @click="changeTab(t.key)">{{ t.name }}</button>
    </div>
    <div class="pg-filter-bar">
      <label>业务员</label>
      <el-select :model-value="filters.userId" clearable filterable aria-label="明细业务员" placeholder="全部业务员" class="pg-w-160" @update:model-value="v => setFilter('userId', v)">
        <el-option v-for="u in users" :key="u.user_id" :label="u.name" :value="u.user_id" />
      </el-select>
      <label>战队</label>
      <el-select :model-value="filters.departmentId" clearable aria-label="明细战队" placeholder="全部战队" class="pg-w-140" @update:model-value="v => setFilter('departmentId', v)">
        <el-option v-for="t in teams" :key="t.department_id" :label="t.name" :value="t.department_id" />
      </el-select>
      <label>时间范围</label>
      <el-date-picker
        :model-value="filters.range" type="daterange" value-format="YYYY-MM-DD"
        start-placeholder="开始日期" end-placeholder="结束日期" class="pg-w-250"
        @update:model-value="v => setFilter('range', v || [])" />
      <span class="pg-sum" v-if="summary">
        共 <b>{{ fmtInt(summary.order_count) }}</b> 条 · 合计 <b>{{ fmtUsd(summary.amount_usd, { cents: true }) }}</b>
        <template v-if="summary.customer_count != null"> · 客户 <b>{{ fmtInt(summary.customer_count) }}</b> 位</template>
      </span>
    </div>
    <ListPageStatus v-if="loadError" :error="loadError" :has-data="false" @retry="load" />
    <p v-if="waitingPeriod" class="pg-empty">所选周期尚未开始</p>
    <div v-else class="pg-table-wrap" v-loading="loading">
      <table class="pg-tbl">
        <thead>
          <tr>
            <th>订单号</th><th>客户公司</th><th>国家</th><th class="pg-r">金额(USD)</th>
            <th>业绩入账日期</th><th>业务员</th><th>指标标记</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="o in items" :key="o.fact_key || o.order_id">
            <td>{{ o.order_no }}</td>
            <td>{{ o.customer_name }}</td>
            <td>{{ o.country }}</td>
            <td class="pg-r"><b>{{ fmtUsd(o.amount_usd, { cents: true }) }}</b></td>
            <td>{{ o.account_date }}</td>
            <td>{{ o.owner_name }}</td>
            <td>
              <span v-for="f in o.flags || []" :key="f" class="pg-tag" :class="f === '新签' ? 'pg-blue' : 'pg-green'" style="margin-right:4px">{{ f }}</span>
            </td>
          </tr>
          <tr v-if="!items.length && !loading && !loadError"><td colspan="7" class="pg-empty">当前筛选无数据</td></tr>
        </tbody>
        <tfoot v-if="summary">
          <tr class="pg-row-total">
            <td>合计（全部 {{ fmtInt(total) }} 条）</td><td colspan="2"></td>
            <td class="pg-r">{{ fmtUsd(summary.amount_usd, { cents: true }) }}</td>
            <td colspan="3"></td>
          </tr>
        </tfoot>
      </table>
    </div>
    <div class="pg-pager">
      <span>每页 {{ pageSize }} 条 · 共 {{ total }} 条</span>
      <button aria-label="上一页" :disabled="page <= 1" @click="changePage(page - 1)">‹</button>
      <template v-for="(p, i) in pageWindow" :key="i">
        <span v-if="p === '…'">…</span>
        <button v-else :class="{ 'pg-active': p === page }" @click="changePage(p)">{{ p }}</button>
      </template>
      <button aria-label="下一页" :disabled="page >= pages" @click="changePage(page + 1)">›</button>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { perfGoalApi } from '@/api/perfGoal'
import { fmtInt, fmtUsd } from '../helpers'

const props = defineProps({
  users: { type: Array, default: () => [] },
  teams: { type: Array, default: () => [] },
  presetUserId: { type: [String, Number], default: null },
  presetDepartmentId: { type: [String, Number], default: null },
  periodRange: { type: Array, required: true },
  periodNotStarted: Boolean,
  presetListedOnly: Boolean,
  analysisLabel: { type: String, default: '' },
})

const tabs = [
  { key: 'gmv', name: 'GMV订单' },
  { key: 'new_sign', name: '新签客户' },
  { key: 'repeat_customers', name: '复购客户' },
  { key: 'repeat_amount', name: '复购金额' },
]
const tab = ref('gmv')
const filters = reactive({ userId: props.presetUserId, departmentId: props.presetDepartmentId, range: [...props.periodRange], listedOnly: props.presetListedOnly })
const loadError = ref('')
const detailsAdjusted = computed(() => String(filters.userId || '') !== String(props.presetUserId || '') || String(filters.departmentId || '') !== String(props.presetDepartmentId || '') || JSON.stringify(filters.range) !== JSON.stringify(props.periodRange) || filters.listedOnly !== props.presetListedOnly)
const waitingPeriod = computed(() => props.periodNotStarted && JSON.stringify(filters.range) === JSON.stringify(props.periodRange))
const items = ref([]), summary = ref(null), total = ref(0)
const page = ref(1), pageSize = 15, loading = ref(false)
let requestSeq = 0

const pages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
const pageWindow = computed(() => {
  const win = []
  for (let i = 1; i <= pages.value; i++) {
    if (i === 1 || i === pages.value || Math.abs(i - page.value) <= 2) win.push(i)
  }
  const out = []
  let last = 0
  win.forEach(i => { if (i - last > 1) out.push('…'); out.push(i); last = i })
  return out
})

async function load() {
  const seq = ++requestSeq
  loadError.value = ''; items.value = []; summary.value = null; total.value = 0
  if (waitingPeriod.value) { loading.value = false; return }
  if (filters.range?.length !== 2 || filters.range[0] > filters.range[1]) { loadError.value = '请选择有效的开始和结束日期'; loading.value = false; return }
  loading.value = true
  try {
    const res = await perfGoalApi.metricOrders({
      metric: tab.value,
      listed_only: filters.listedOnly || undefined,
      user_id: filters.userId || undefined,
      department_id: filters.departmentId || undefined,
      date_from: filters.range?.[0] || undefined,
      date_to: filters.range?.[1] || undefined,
      page: page.value,
      page_size: pageSize,
    }, { suppressToast: true })
    if (seq !== requestSeq) return
    items.value = res.items || []
    summary.value = res.summary || null
    total.value = res.total ?? items.value.length
  } catch {
    if (seq === requestSeq) loadError.value = '指标明细读取失败，请重试'
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}
function changeTab(key) { tab.value = key; page.value = 1; load() }
function setFilter(key, value) {
  filters[key] = value
  if (key === 'userId') { filters.listedOnly = false; if (value) filters.departmentId = null }
  if (key === 'departmentId') { filters.listedOnly = false; if (value) filters.userId = null }
  page.value = 1; load()
}
function changePage(p) { if (p >= 1 && p <= pages.value) { page.value = p; load() } }

function applyDefaults() {
  filters.userId = props.presetUserId; filters.departmentId = props.presetDepartmentId
  filters.range = [...props.periodRange]; filters.listedOnly = props.presetListedOnly; page.value = 1; load()
}
watch(() => [props.presetUserId, props.presetDepartmentId, props.periodRange.join('|'), props.periodNotStarted, props.presetListedOnly], applyDefaults, { immediate: true })
</script>
