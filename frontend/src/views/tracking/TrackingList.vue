<template>
  <div class="tracking-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="tracking-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <!-- 看板：运单状态概览 -->
    <ListPageStatus :paged="false" :error="statsResource.errorMessage.value" :loading="statsResource.loading.value" :has-data="statsResource.hasLoaded.value" @retry="fetchStats" />
    <section class="kanban" v-if="stats">
      <div class="kanban-header">
        <div class="kanban-title">
          <span class="kanban-accent"></span>
          <h3>运单状态概览</h3>
          <span class="kanban-realtime">实时</span>
        </div>
        <span class="kanban-updated" v-if="lastUpdated">
          <el-icon><Clock /></el-icon>
          更新于 {{ lastUpdated }}
        </span>
      </div>

      <div class="kanban-grid">
        <div
          v-for="(item, i) in kanbanItems"
          :key="item.key"
          class="kanban-card"
          :class="{ 'is-active': activeKanban === item.key }"
          :style="{
            background: item.bg,
            borderColor: activeKanban === item.key ? item.color : item.border,
            boxShadow: activeKanban === item.key ? `0 0 0 2px ${item.color}33` : undefined,
            animationDelay: `${i * 70}ms`,
          }"
          @click="handleKanbanClick(item)"
        >
          <div class="kanban-card__bg-icon" :style="{ color: item.color }">
            <el-icon><component :is="item.icon" /></el-icon>
          </div>

          <div class="kanban-card__inner">
            <div class="kanban-card__top">
              <div class="kanban-card__icon" :style="{ background: `${item.color}1f`, color: item.color }">
                <el-icon><component :is="item.icon" /></el-icon>
              </div>
            </div>

            <div class="kanban-card__value">
              <span class="value" :style="{ color: item.color }">{{ getStatValue(item.statKey) }}</span>
              <span class="desc">{{ item.desc }}</span>
            </div>

            <div class="kanban-card__foot">
              <span class="label">{{ item.label }}</span>
              <span class="progress">
                <span class="progress__fill" :style="{ width: `${getProgress(item.statKey)}%`, background: item.color }"></span>
              </span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- 筛选栏 + 操作行 + 表格 + 分页统一收进表格卡片（List Page Spec / Action Bar Spec） -->
    <div ref="panelRef" class="table-card tracking-panel">
    <FilterBar :loading="loading" :pending="hasPendingSearch" @search="searchList" @reset="resetFilters">
      <el-input v-model="keyword" placeholder="运单号 / 收件人" clearable class="filter-w-md">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-select v-model="statusFilter" placeholder="状态" clearable class="filter-w-sm">
        <el-option label="待查询" value="pending" />
        <el-option label="运输中" value="in_transit" />
        <el-option label="清关中" value="customs" />
        <el-option label="派送中" value="out_for_delivery" />
        <el-option label="已签收" value="delivered" />
        <el-option label="异常" value="exception" />
        <el-option label="已退回" value="returned" />
      </el-select>
      <el-select v-model="carrierFilter" placeholder="物流商" clearable class="filter-w-sm">
        <el-option label="DHL" value="DHL" />
        <el-option label="FedEx" value="FEDEX" />
        <el-option label="UPS" value="UPS" />
        <el-option label="TNT" value="TNT" />
      </el-select>
      <el-select v-model="activeFilter" placeholder="跟踪状态" clearable class="filter-w-sm">
        <el-option label="跟踪中" value="1" />
        <el-option label="已结束" value="0" />
      </el-select>
    </FilterBar>

    <!-- 操作行：主操作按钮组 + TableTools 四图标（Action Bar Spec） -->
    <div class="action-bar">
      <GlassButton v-permission="'tracking:write'" variant="secondary" left-icon="Refresh" @click="handleScanStaging">扫描暂存</GlassButton>
      <GlassButton v-permission="'tracking:write'" variant="secondary" left-icon="Loading" @click="handlePoll">批量轮询</GlassButton>
      <TableTools
        v-model:visible-keys="visibleKeys"
        v-model:density="density"
        :columns="columnDefs"
        :fullscreen="isFullscreen"
        :loading="loading" @refresh="fetchList"
        @fullscreen="toggleFullscreen"
      />
    </div>

    <ListPageStatus v-if="hasData && errorMessage" :error="errorMessage" :loading="loading" :has-data="hasData" :data-page="dataPage" @retry="fetchList" />
      <el-table
      ref="tableRef"
      :data="tableData"
      v-loading="loading"
      :max-height="isFullscreen ? undefined : 640"
      @sort-change="changeSort"
      class="list-table"
      :class="densityClass"
      border
    >
      <template #empty><ListPageStatus :error="errorMessage" :loading="loading" @retry="fetchList">
        <el-empty :image-size="96" :description="hasActiveFilters ? '没有符合条件的运单' : '暂无数据'">
          <GlassButton v-if="hasActiveFilters" left-icon="RefreshLeft" @click="resetFilters">重置筛选</GlassButton>
        </el-empty>
      </ListPageStatus></template>
      <el-table-column v-if="visibleKeys.includes('waybill-no')" prop="waybill_no" label="运单号" min-width="140" max-width="200" show-overflow-tooltip sortable="custom">
        <template #default="{ row }">
          <GlassButton variant="link" class="primary-link" @click="goDetail(row)">{{ row.waybill_no }}</GlassButton>
        </template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('carrier-name')" prop="carrier_name" label="物流商" min-width="100" max-width="140" show-overflow-tooltip sortable="custom" />
      <el-table-column v-if="visibleKeys.includes('receiver-name')" prop="receiver_name" label="收件人" min-width="110" max-width="170" show-overflow-tooltip />
      <el-table-column v-if="visibleKeys.includes('receiver-country')" prop="receiver_country" label="国家" min-width="90" max-width="130" show-overflow-tooltip />
      <el-table-column v-if="visibleKeys.includes('current-status')" prop="current_status" label="状态" min-width="110" max-width="150" sortable="custom">
        <template #default="{ row }">
          <StatusBadge :type="statusTagType(row.current_status)" size="small" effect="plain">
            {{ statusText(row.current_status) }}
          </StatusBadge>
        </template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('current-status-text')" prop="current_status_text" label="最新动态" min-width="190" max-width="340" show-overflow-tooltip />
      <el-table-column v-if="visibleKeys.includes('current-location')" prop="current_location" label="当前位置" min-width="130" max-width="220" show-overflow-tooltip />
      <el-table-column v-if="visibleKeys.includes('estimated-delivery')" label="预计送达" min-width="90" max-width="130" show-overflow-tooltip>
        <template #default="{ row }">
          {{ row.estimated_delivery_date ? fmtDateShort(row.estimated_delivery_date) : '-' }}
        </template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('last-event-time')" label="最新时间" min-width="160" max-width="200" show-overflow-tooltip>
        <template #default="{ row }">{{ row.last_event_time || '-' }}</template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('dingtalk-user-name')" prop="dingtalk_user_name" label="提交人" min-width="100" max-width="140" show-overflow-tooltip />
      <el-table-column v-if="visibleKeys.includes('short-link')" label="短链接" min-width="100" max-width="140">
        <template #default="{ row }">
          <GlassButton v-if="row.short_link" variant="link" left-icon="CopyDocument" @click="copyLink(row.short_link)">
            复制
          </GlassButton>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('tracking-active')" label="跟踪" min-width="110" max-width="150">
        <template #default="{ row }">
          <StatusBadge :type="row.is_active ? 'success' : 'info'" size="small" effect="plain">
            {{ row.is_active ? '进行中' : '已结束' }}
          </StatusBadge>
        </template>
      </el-table-column>
      <el-table-column class-name="table-action-column" label="操作" min-width="130" max-width="180" fixed="right">
        <template #default="{ row }">
          <GlassButton v-permission="'tracking:write'" variant="link" left-icon="Refresh" @click="handleRefresh(row)">
            刷新
          </GlassButton>
          <GlassButton
            v-if="authStore.hasAnyPermission(['tracking:delete'])"
            variant="link"
            left-icon="Delete"
            style="color: var(--el-color-danger)"
            @click="handleDelete(row)"
          >
            删除
          </GlassButton>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      class="pager"
      v-model:current-page="page"
      v-model:page-size="pageSize"
      :total="total"
      layout="total, sizes, prev, pager, next"
      :page-sizes="[20, 50, 100]"
      @current-change="handlePageChange"
      @size-change="handleSizeChange"
    />
    </div>
  </div>
</template>

<script setup>
import { useListPage } from '@/composables/useListPage'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { toRef } from 'vue'

import { TRACKING_STATUS, TRACKING_STATUS_LABELS as STATUS_MAP, TRACKING_STATUS_TYPES as STATUS_TAG } from './trackingStatus.js'
import { resolveStatus } from '@/utils/status'
import { msgSuccessText, confirmAction } from '@/utils/feedback'
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'

import { getShipmentList, getTrackingStats, refreshShipment, deleteShipment, triggerScanStaging, triggerPoll } from '@/api/tracking'
import { useAuthStore } from '@/stores/auth'
import { useTableSort } from '@/composables/useTableSort'
import { useTrackingTableView } from './composables/useTrackingTableView'
import TableTools from '@/components/TableTools.vue'
import { formatBeijingDate, formatBeijingDateTime } from '@/utils/datetime'

const router = useRouter()
const authStore = useAuthStore()
const orderSort = useTableSort()

// 表格视图状态（列显隐/密度/全屏）走全局基建 useTableView（Action Bar Spec）
const { columnDefs, density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useTrackingTableView()

const tableRef = ref()

const statsResource = useAsyncResource(async (_, { signal }) => {
  const response = await getTrackingStats(undefined, { signal, suppressToast: true })
  return { stats: response.data, updatedAt: formatUpdatedAt() }
})
const stats = computed(() => statsResource.data.value?.stats || null)
const lastUpdated = computed(() => statsResource.data.value?.updatedAt || '')
const activeKanban = ref('')
const listState = useListPage(async (params, { signal }) => {
  const response = await getShipmentList(params, { signal, suppressToast: true })
  return { items: response.data.items || [], total: response.data.total || 0 }
}, { searchForm: { keyword: '', status: '', carrier: '', is_active: '' } })
const { loading, list: tableData, total, page, pageSize, searchForm, appliedSearchForm, errorMessage, hasData, dataPage, hasPendingSearch, fetchList, handleSearch, handleReset: handleReset, handlePageChange, handleSizeChange, refreshCreate, refreshUpdate, refreshRemove } = listState
const keyword = toRef(searchForm, 'keyword')
const statusFilter = toRef(searchForm, 'status')
const carrierFilter = toRef(searchForm, 'carrier')
const activeFilter = toRef(searchForm, 'is_active')
function changeSort(event) { orderSort.onSortChange(event); return listState.handleSortChange(orderSort.sortParams.value) }

const kanbanItems = [
  {
    key: 'total', statKey: 'total', statusValue: '',
    label: '全部运单', desc: '累计',
    icon: 'Box', color: '#2563eb',
    bg: 'linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%)', border: '#bfdbfe',
  },
  {
    key: 'in_transit', statKey: 'in_transit', statusValue: 'in_transit',
    label: '运输中', desc: '在途',
    icon: 'Van', color: '#d97706',
    bg: 'linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%)', border: '#fde68a',
  },
  {
    key: 'customs', statKey: 'customs', statusValue: 'customs',
    label: '清关中', desc: '等待放行',
    icon: 'Ship', color: '#7c3aed',
    bg: 'linear-gradient(135deg, #f5f3ff 0%, #ede9fe 100%)', border: '#ddd6fe',
  },
  {
    key: 'delivered', statKey: 'delivered', statusValue: 'delivered',
    label: '已签收', desc: '已完成',
    icon: 'CircleCheck', color: '#059669',
    bg: 'linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%)', border: '#a7f3d0',
  },
  {
    key: 'exception', statKey: 'exception', statusValue: 'exception',
    label: '异常', desc: '需关注',
    icon: 'Warning', color: '#dc2626',
    bg: 'linear-gradient(135deg, #fef2f2 0%, #fee2e2 100%)', border: '#fecaca',
  },
]

function getStatValue(key) {
  return stats.value?.[key] ?? 0
}

function getProgress(key) {
  const totalCount = stats.value?.total || 0
  if (key === 'total') return totalCount > 0 ? 100 : 0
  if (!totalCount) return 0
  const v = stats.value?.[key] || 0
  return Math.min(Math.round((v / totalCount) * 100), 100)
}

const hasActiveFilters = computed(() => Boolean(appliedSearchForm.value.keyword || appliedSearchForm.value.status || appliedSearchForm.value.carrier || appliedSearchForm.value.is_active))

// 重置 = 清空筛选（含看板高亮）+ 回第 1 页 + 重新加载
function resetFilters() { activeKanban.value = ''; return handleReset() }


function handleKanbanClick(item) {
  if (activeKanban.value === item.key) {
    activeKanban.value = ''
    statusFilter.value = ''
  } else {
    activeKanban.value = item.key
    statusFilter.value = item.statusValue
  }
  return handleSearch()
}

function formatUpdatedAt(d = new Date()) {
  return formatBeijingDateTime(d, { seconds: false })
}




function statusText(s) { return resolveStatus(s, TRACKING_STATUS).label }
function statusTagType(s) { return resolveStatus(s, TRACKING_STATUS).type }

// 状态下拉变更时，同步看板高亮（'total' 卡仅由点击触发，不随空筛选自动激活）
function searchList() {
  const val = statusFilter.value
  if (!val) {
    activeKanban.value = ''
  } else {
    const hit = kanbanItems.find((it) => it.statusValue === val)
    activeKanban.value = hit ? hit.key : ''
  }
  return handleSearch()
}

const fetchStats = () => statsResource.load()
watch(() => JSON.stringify([authStore.user?.id, authStore.roles, authStore.permissions]), () => {
  statsResource.clear(); fetchStats()
})


async function handleRefresh(row) {
  try {
    await refreshShipment(row.waybill_no)
    msgSuccessText('刷新完成')
    refreshUpdate()
    fetchStats()
  } catch { /* handled by interceptor */ }
}

async function handleDelete(row) {
  try {
    await confirmAction(`确定删除运单 ${row.waybill_no}？`, '删除确认', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await deleteShipment(row.waybill_no)
    msgSuccessText('已删除')
    refreshRemove()
    fetchStats()
  } catch { /* cancelled or handled by interceptor */ }
}

async function handleScanStaging() {
  try {
    const res = await triggerScanStaging()
    const d = res.data
    msgSuccessText(`扫描完成：${d.success} 新增，${d.reactivated} 恢复，${d.duplicate} 重复，${d.error} 异常`)
    refreshCreate()
    fetchStats()
  } catch { /* handled by interceptor */ }
}

async function handlePoll() {
  try {
    const res = await triggerPoll()
    const d = res.data
    msgSuccessText(`轮询完成：${d.total} 条，成功 ${d.ok}，失败 ${d.error}`)
    refreshUpdate()
    fetchStats()
  } catch { /* handled by interceptor */ }
}

function goDetail(row) {
  router.push(`/tracking/${row.waybill_no}`)
}

function copyLink(link) {
  navigator.clipboard.writeText(link).then(() => {
    msgSuccessText('短链接已复制')
  })
}

function fmtDateShort(dateStr) {
  const formatted = formatBeijingDate(dateStr)
  if (formatted === '-') return '-'
  const [, month, day] = formatted.split('-')
  return `${Number(month)}/${Number(day)}`
}

onMounted(fetchStats)
</script>

<style scoped src="./tracking-list.css"></style>
