<template>
  <div class="pg-card">
    <div class="pg-card-title">
      <h2>个人排名</h2>
      <span class="pg-note">默认按 GMV 完成率排序，点击表头可切换排序</span>
    </div>
    <div class="pg-table-wrap" v-loading="loading">
      <table class="pg-tbl">
        <thead>
          <tr>
            <th class="pg-c">排名</th><th>姓名</th><th>战队</th>
            <th v-for="h in sortableHeaders" :key="h.key" class="pg-sortable" :class="h.cls" @click="toggleSort(h.key)">
              {{ h.label }}<span class="pg-arrow">{{ sortKey === h.key ? (order === 'desc' ? '▼' : '▲') : '' }}</span>
            </th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr class="pg-row-total">
            <td></td>
            <td>{{ scope === 'team' ? `队内有目标成员合计（${listed.length}人）` : `主名单合计（${listed.length}人）` }}</td>
            <td>—</td>
            <td class="pg-r">{{ fmtUsd(totals.gmv.target) }}</td>
            <td class="pg-r">{{ fmtUsd(totals.gmv.achieved) }}</td>
            <td class="pg-r">{{ fmtRate(totals.gmv.rate) }}</td>
            <td class="pg-c">{{ fmtInt(totals.new_sign.achieved) }} / {{ fmtInt(totals.new_sign.target) }} · {{ fmtRate(totals.new_sign.rate) }}</td>
            <td class="pg-c">{{ fmtInt(totals.repeat_customers.achieved) }} / {{ fmtInt(totals.repeat_customers.target) }} · {{ fmtRate(totals.repeat_customers.rate) }}</td>
            <td class="pg-c">{{ fmtUsd(totals.repeat_amount.achieved) }} / {{ fmtUsd(totals.repeat_amount.target) }} · {{ fmtRate(totals.repeat_amount.rate) }}</td>
            <td class="pg-r">
              <span v-if="totalDelta != null" class="pg-delta" :class="totalDelta >= 0 ? 'pg-up' : 'pg-down'">{{ fmtPp(totalDelta) }}</span>
              <template v-else>—</template>
            </td>
            <td>—</td>
          </tr>
          <tr v-for="row in listed" :key="row.user_id" :class="{ 'pg-row-hl': row.user_id === highlightUserId }" :data-user-id="row.user_id">
            <td class="pg-c">{{ row.rank }}</td>
            <td><b>{{ row.name }}</b> <span v-if="row.is_captain" class="pg-tag pg-blue">队长</span></td>
            <td>{{ row.team_name }}</td>
            <td class="pg-r">{{ fmtUsd(row.gmv?.target) }}</td>
            <td class="pg-r"><b>{{ fmtUsd(row.gmv?.achieved) }}</b></td>
            <td class="pg-r" :style="{ color: rateColor(row.gmv?.rate), fontWeight: 600 }">{{ fmtRate(row.gmv?.rate) }}</td>
            <td v-for="k in ['new_sign', 'repeat_customers', 'repeat_amount']" :key="k" class="pg-c">
              <div>{{ fmtMetric(k, row[k]?.achieved) }} <span style="color:var(--pg-faint)">/ {{ fmtMetric(k, row[k]?.target) }}</span></div>
              <div style="font-size:11.5px" :style="{ color: rateColor(row[k]?.rate) }">{{ fmtRate(row[k]?.rate) }}</div>
            </td>
            <td class="pg-r">
              <span v-if="row.delta_pp != null" class="pg-delta" :class="row.delta_pp >= 0 ? 'pg-up' : 'pg-down'">{{ fmtPp(row.delta_pp) }}</span>
              <template v-else>—</template>
            </td>
            <td><span class="pg-tag" :class="`pg-${normalizeStatus(row.status).tag}`">{{ normalizeStatus(row.status).text }}</span></td>
          </tr>
          <tr v-for="row in unlisted" :key="`x-${row.user_id}`" class="pg-row-dim">
            <td class="pg-c">—</td>
            <td>{{ row.name }} <span class="pg-tag pg-gray">未设目标</span></td>
            <td>{{ row.team_name }}</td>
            <td class="pg-r">—</td>
            <td class="pg-r">{{ fmtUsd(row.gmv?.achieved) }}</td>
            <td class="pg-r">—</td>
            <td v-for="k in ['new_sign', 'repeat_customers', 'repeat_amount']" :key="k" class="pg-c">
              <div>{{ fmtMetric(k, row[k]?.achieved) }} / —</div>
              <div style="font-size:11.5px">—</div>
            </td>
            <td class="pg-r">—</td>
            <td><span class="pg-tag pg-gray">未设目标</span></td>
          </tr>
          <tr v-if="!listed.length && !unlisted.length && !loading">
            <td colspan="11" class="pg-empty">暂无排名数据</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="pg-footnote">周期：{{ periodLabel }} · 时间进度 {{ timeProgress ?? '—' }}%；未设目标人员置灰列于表尾，不计入合计。</div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { fmtUsd, fmtInt, fmtMetric, fmtRate, fmtPp, normalizeStatus, sumMetricCells, deltaPp } from '../helpers'

const props = defineProps({
  rows: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  timeProgress: { type: Number, default: null },
  periodLabel: { type: String, default: '' },
  scope: { type: String, default: 'company' },
  highlightUserId: { type: [String, Number], default: null },
  sort: { type: String, default: 'gmv_rate' },
  order: { type: String, default: 'desc' },
})
const emit = defineEmits(['sort-change'])

const sortableHeaders = [
  { key: 'gmv_target', label: 'GMV目标', cls: 'pg-r' },
  { key: 'gmv_achieved', label: 'GMV完成', cls: 'pg-r' },
  { key: 'gmv_rate', label: 'GMV完成率', cls: 'pg-r' },
  { key: 'new_sign_rate', label: '新签 完成/目标', cls: 'pg-c' },
  { key: 'repeat_customers_rate', label: '复购客户 完成/目标', cls: 'pg-c' },
  { key: 'repeat_amount_rate', label: '复购金额 完成/目标', cls: 'pg-c' },
  { key: 'delta_pp', label: '与时间进度差', cls: 'pg-r' },
]
const sortKey = ref(props.sort), order = ref(props.order)
watch(() => [props.sort, props.order], ([s, o]) => { sortKey.value = s; order.value = o })
function toggleSort(key) {
  if (sortKey.value === key) order.value = order.value === 'desc' ? 'asc' : 'desc'
  else { sortKey.value = key; order.value = 'desc' }
  emit('sort-change', { sort: sortKey.value, order: order.value })
}

const listed = computed(() => props.rows.filter(r => r.listed !== false))
const unlisted = computed(() => props.rows.filter(r => r.listed === false))
const totals = computed(() => sumMetricCells(listed.value))
const totalDelta = computed(() => deltaPp(totals.value.gmv.rate, props.timeProgress))

const rateColor = rate => {
  if (rate == null) return 'var(--pg-faint)'
  const tp = props.timeProgress ?? 100
  return rate >= 100 ? 'var(--pg-green)' : rate >= tp ? 'var(--pg-primary)' : 'var(--pg-red)'
}

watch(() => [props.highlightUserId, props.rows], async ([id]) => {
  if (id == null) return
  await nextTick()
  document.querySelector(`.perf-goal-page tr.pg-row-hl[data-user-id="${id}"]`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
}, { deep: true })
</script>
