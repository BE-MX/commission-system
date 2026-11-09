<template>
  <div ref="panelRef" class="table-card customer-overview">
    <div class="customer-metrics">
      <OverviewMetricCard v-for="metric in metrics" :key="metric.key" :label="metric.label"
                          :value="counts?.[metric.key === 'all' ? 'total' : metric.key] ?? '—'" :tone="metric.tone" :icon="metric.icon"
                          interactive :selected="list.appliedSearchForm.value.deal_status === metric.key"
                          @click="selectDeal(metric.key)" />
    </div>
    <div class="action-bar customer-tools">
      <el-select v-model="list.searchForm.scope" aria-label="责任范围" class="scope-control" @change="changeScope">
        <el-option v-for="scope in scopes" :key="scope.key" :label="scope.label" :value="scope.key" />
      </el-select>
      <GlassButton v-if="mobile" variant="outline" left-icon="Filter" @click="filtersOpen = true">筛选</GlassButton>
      <TableTools v-else v-model:visible-keys="visibleKeys" v-model:density="density" :columns="columns"
                  :loading="list.loading.value" :fullscreen="isFullscreen" @refresh="refresh" @fullscreen="toggleFullscreen" />
    </div>
    <DetailDrawer v-if="mobile" v-model="filtersOpen" title="客户筛选">
      <CustomerOverviewFilters :form="list.searchForm" :regions="regions" :loading="list.loading.value"
                               :pending="list.hasPendingSearch.value" :assignees="assignees" @search="search" @reset="reset" />
    </DetailDrawer>
    <CustomerOverviewFilters v-else :form="list.searchForm" :regions="regions" :loading="list.loading.value"
                             :pending="list.hasPendingSearch.value" :assignees="assignees" @search="search" @reset="reset" />
    <ListPageStatus v-if="list.hasData.value || mobile" :error="list.errorMessage.value" :loading="list.loading.value"
                    :has-data="list.hasData.value" :data-page="list.dataPage.value" @retry="refresh">
      <el-empty v-if="mobile && !list.hasData.value" description="当前范围内暂无符合条件的客户" />
    </ListPageStatus>
    <div v-if="mobile" v-loading="list.loading.value" class="customer-cards">
      <article v-for="row in list.list.value" :key="row.id" class="customer-card">
        <header><strong>{{ row.shop_name }}</strong><span>{{ dealLabel(row) }}</span></header>
        <p>{{ regionLabel(row) }} · {{ row.assignee_name || '暂无跟进人' }}</p>
        <p>{{ labelFor(COLLABORATION_STATUS, row.collaboration_status) }} · {{ row.last_followup_date || '从未联系' }}</p>
        <div class="customer-row-actions">
          <GlassButton v-if="row.can_record" v-permission="'domestic_followup:write'" variant="link" @click="record(row)">记跟进</GlassButton>
          <GlassButton variant="link" @click="openDetail(row)">{{ detailLabel(row) }}</GlassButton>
        </div>
      </article>
    </div>
    <el-table v-else :data="list.list.value" v-loading="list.loading.value" row-key="id" border class="list-table"
              :class="densityClass" v-sticky-scrollbar @sort-change="sort">
      <template #empty>
        <ListPageStatus :error="list.errorMessage.value" :loading="list.loading.value" :has-data="false" @retry="refresh">
          <el-empty :image-size="96" description="当前范围内暂无符合条件的客户" />
        </ListPageStatus>
      </template>
      <el-table-column v-if="visibleKeys.includes('shop_name')" label="客户" prop="shop_name" min-width="150" sortable="custom" fixed show-overflow-tooltip>
        <template #default="{ row }">
          <GlassButton variant="link" @click="$emit('detail', row)">{{ row.shop_name }}</GlassButton>
          <small v-if="row.custom_code">{{ row.custom_code }}</small>
        </template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('province')" label="地区" prop="province" min-width="110" show-overflow-tooltip>
        <template #default="{ row }">{{ regionLabel(row) }}</template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('phone')" label="联系方式" prop="phone" min-width="145">
        <template #default="{ row }">
          <small v-if="!row.can_view_contacts">{{ row.collaboration_status === 'open' ? '接手后可查看' : '联系方式受限' }}</small>
          <template v-else>
            <span v-if="row.contact">{{ row.contact }}</span>
            <GlassButton v-if="row.phone || row.wechat" variant="link" left-icon="CopyDocument" @click="copy(row.phone || row.wechat)">{{ row.phone || row.wechat }}</GlassButton>
            <small v-else>待补联系方式</small>
          </template>
        </template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('deal_status')" label="成交情况" prop="deal_status" min-width="125" show-overflow-tooltip>
        <template #default="{ row }">
          <strong>{{ dealLabel(row) }}</strong>
          <small v-if="row.deal_source">{{ labelFor(DEAL_SOURCE, row.deal_source) }}</small>
          <small v-if="row.deal_conflict">成交与历史资料待核对</small>
        </template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('assignee_name')" label="当前跟进" prop="assignee_name" min-width="130" show-overflow-tooltip>
        <template #default="{ row }">
          <span>{{ row.assignee_name || '暂无跟进人' }}</span>
          <small>{{ labelFor(COLLABORATION_STATUS, row.collaboration_status) }}<template v-if="row.handoff_recipient_name"> · {{ row.handoff_recipient_name }}</template></small>
        </template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('last_followup_date')" label="最近联系" prop="last_followup_date" min-width="155" sortable="custom" show-overflow-tooltip>
        <template #default="{ row }">
          <span>{{ [row.last_followup_date, row.last_followup_author].filter(Boolean).join(' · ') || '从未联系' }}</span>
          <small v-if="row.last_followup_summary">{{ row.last_followup_summary }}</small>
        </template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('next_date')" label="推进 / 下次" prop="next_date" min-width="125" sortable="custom" show-overflow-tooltip>
        <template #default="{ row }">
          <span>{{ labelFor(DEVELOPMENT_STAGE, row.stage) }}</span>
          <small>{{ [row.next_date, ...(row.obstacles || [])].filter(Boolean).join(' · ') || '未安排' }}</small>
        </template>
      </el-table-column>
      <el-table-column label="操作" class-name="table-action-column" min-width="135" fixed="right">
        <template #default="{ row }">
          <GlassButton v-if="row.can_record" v-permission="'domestic_followup:write'" variant="link" @click="record(row)">记跟进</GlassButton>
          <GlassButton variant="link" @click="openDetail(row)">{{ detailLabel(row) }}</GlassButton>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination :current-page="list.page.value" :page-size="list.pageSize.value" :total="list.total.value"
                   :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next"
                   :pager-count="mobile ? 5 : 7" class="pager"
                   @current-change="list.handlePageChange" @size-change="list.handleSizeChange" />
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { CircleCheck, Clock, QuestionFilled, User } from '@element-plus/icons-vue'
import { followupApi } from '@/api/domesticFollowup'
import DetailDrawer from '@/components/DetailDrawer.vue'
import GlassButton from '@/components/GlassButton.vue'
import OverviewMetricCard from '@/components/OverviewMetricCard.vue'
import TableTools from '@/components/TableTools.vue'
import { useListPage } from '@/composables/useListPage'
import { useTableView } from '@/composables/useTableView'
import { copyText } from '@/utils/clipboard'
import { msgError, msgSuccessText } from '@/utils/feedback'
import { COLLABORATION_STATUS, DEAL_SOURCE, DEVELOPMENT_STAGE, dealLabel, labelFor, regionLabel } from '../customerOverview'
import CustomerOverviewFilters from './CustomerOverviewFilters.vue'

const props = defineProps({ defaultScope: { type: String, default: 'mine' } })
const emit = defineEmits(['detail', 'record', 'query-change'])
const scopes = [
  { key: 'mine', label: '我负责' }, { key: 'collaborating', label: '我协作' }, { key: 'available', label: '可接手' },
  { key: 'incoming', label: '交接给我' }, { key: 'authorized', label: '授权范围' },
]
const metrics = [
  { key: 'all', label: '客户数', tone: 'info', icon: User }, { key: 'unwon', label: '未成交', tone: 'warning', icon: Clock },
  { key: 'won', label: '已成交', tone: 'gold', icon: CircleCheck }, { key: 'unknown', label: '待核实', tone: 'violet', icon: QuestionFilled },
]
const columns = [
  { key: 'shop_name', label: '客户', required: true }, { key: 'province', label: '地区' },
  { key: 'phone', label: '联系方式' }, { key: 'deal_status', label: '成交情况' },
  { key: 'assignee_name', label: '当前跟进' }, { key: 'last_followup_date', label: '最近联系' },
  { key: 'next_date', label: '推进 / 下次' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useTableView('domestic-customer-overview', columns)
const counts = ref(null), regions = ref([]), assignees = ref([])
const mobile = ref(false), filtersOpen = ref(false)
let media
const syncMobile = () => { mobile.value = media.matches }
onMounted(() => {
  media = window.matchMedia('(max-width: 768px)')
  syncMobile()
  media.addEventListener('change', syncMobile)
})
onBeforeUnmount(() => media?.removeEventListener('change', syncMobile))

const initialForm = {
  keyword: '', province: '', city: '', deal_status: 'all', scope: props.defaultScope, collaboration_status: '',
  assignee_user_id: '', date_from: '', date_to: '', never_contacted: false, overdue: false, lifecycle_status: '',
}
const list = useListPage(async (params, { signal, isCurrent }) => {
  if (params.date_from && params.date_to && params.date_from > params.date_to) throw new Error('最近联系开始日期不能晚于结束日期')
  const query = Object.fromEntries(Object.entries({ ...params, keyword: params.keyword.trim() }).filter(([, value]) => value))
  const result = await followupApi.customerOverview(query, { signal })
  if (isCurrent()) {
    counts.value = result.counts
    regions.value = result.regions || []
    assignees.value = result.assignees || []
  }
  return result
}, { searchForm: initialForm })

function clearRows() {
  list.cancel()
  list.list.value = []
  list.total.value = 0
  list.hasLoaded.value = false
  counts.value = null
  emit('query-change')
}
function search() {
  clearRows()
  filtersOpen.value = false
  list.handleSearch()
}
function changeScope(scope) {
  clearRows()
  regions.value = []
  assignees.value = []
  list.restoreViewState({ searchForm: { ...list.appliedSearchForm.value, scope }, sortParams: list.appliedSort.value, pageSize: list.pageSize.value })
}
function selectDeal(deal_status) {
  clearRows()
  list.restoreViewState({ searchForm: { ...list.appliedSearchForm.value, deal_status }, sortParams: list.appliedSort.value, pageSize: list.pageSize.value })
}
function reset() {
  clearRows()
  filtersOpen.value = false
  list.restoreViewState({ searchForm: { ...initialForm, scope: list.appliedSearchForm.value.scope }, sortParams: list.appliedSort.value, pageSize: list.pageSize.value })
}
function sort({ prop, order }) {
  list.handleSortChange(order ? { sort_field: prop, sort_order: order === 'ascending' ? 'asc' : 'desc' } : {})
}
function refresh() { return list.refreshUpdate() }
function record(row) { emit('record', { ...row, writable: true }) }
function openDetail(row) { emit('detail', row, row.can_claim ? 'claim' : null) }
function detailLabel(row) {
  if (row.can_claim) return '接手跟进'
  if (row.incoming) return '处理交接'
  return '查看'
}
async function copy(value) {
  if (await copyText(value)) msgSuccessText('已复制联系方式')
  else msgError('复制失败，请手动选取')
}
defineExpose({ refresh })
</script>

<style scoped>
.customer-overview { min-width: 0; }
.customer-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 12px 0; }
.customer-tools { display: flex; align-items: center; gap: 12px; justify-content: space-between; }
.scope-control { width: 155px; }
small { display: block; color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; }
.customer-cards { display: grid; gap: 10px; }
.customer-card { padding: 12px; border: 1px solid var(--border-color); border-radius: 12px; }
.customer-card header, .customer-row-actions { display: flex; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.customer-card p { margin: 6px 0; color: var(--text-secondary); }
@media (max-width: 768px) {
  .customer-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .customer-overview :deep(.pager) { justify-content: center; flex-wrap: wrap; padding-inline: 0; }
}
</style>
