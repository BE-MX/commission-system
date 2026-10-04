<template>
  <div class="workspace-orders">
    <section class="lg-card panel">
      <h3>订单明细（只读）</h3>
      <ListPageStatus v-if="orderState.hasData.value" :error="orderState.errorMessage.value" :loading="ordersLoading" :has-data="true" :data-page="orderState.dataPage.value" @retry="loadOrders" />
      <el-table v-loading="ordersLoading" class="list-table" :data="orders" size="small" border @sort-change="orderState.handleSortChange($event.order ? { sort_field: $event.prop, sort_order: $event.order === 'ascending' ? 'asc' : 'desc' } : {})">
        <template #empty><ListPageStatus :error="orderState.errorMessage.value" :loading="ordersLoading" @retry="loadOrders"><el-empty description="暂无订单明细" :image-size="96" /></ListPageStatus></template>
        <el-table-column sortable="custom" prop="order_no" label="订单号" min-width="120" show-overflow-tooltip />
        <el-table-column sortable="custom" prop="effective_date" label="生效日" min-width="110" />
        <el-table-column sortable="custom" prop="order_type" label="类型" min-width="80" />
        <el-table-column sortable="custom" prop="status" label="状态" min-width="90" />
        <el-table-column sortable="custom" prop="amount" label="原币金额" min-width="130">
          <template #default="{ row }">
            <span v-if="row.amount != null">{{ formatMoney(row.amount, { missing: '—' }) }} {{ row.currency || '' }}</span>
            <span v-else class="hint">未知 {{ row.amount_reason ? `(${row.amount_reason})` : '' }}</span>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination class="pager" v-model:current-page="orderPage" v-model:page-size="orderPageSize" :page-sizes="[20, 50, 100]" :total="orderTotal" layout="total, sizes, prev, pager, next" @current-change="handlePageChange" @size-change="handleSizeChange" />
    </section>

    <section class="lg-card panel">
      <h3>结构分析 <span class="hint">币种/单位不混加；覆盖率分母来自服务端</span></h3>
      <ListPageStatus :error="analyticsResource.errorMessage.value" :loading="analyticsResource.loading.value" :has-data="analyticsResource.hasData.value" @retry="loadAnalytics()" />
      <div class="toolbar">
        <el-select v-model="dimension" size="small" style="width: 130px" @change="loadAnalytics()">
          <el-option v-for="item in ORDER_ANALYTICS_DIMENSIONS" :key="item.value" v-bind="item" />
        </el-select>
        <el-select v-model="measure" size="small" style="width: 140px" @change="loadAnalytics()">
          <el-option v-for="item in ORDER_ANALYTICS_MEASURES" :key="item.value" v-bind="item" />
        </el-select>
        <span class="hint">
          有效订单 {{ analytics.eligibleOrderCount }} · 纳入 {{ analytics.includedCount }} · 未知 {{ analytics.unknownCount }}
        </span>
      </div>
      <div v-for="group in analytics.groups" :key="group.key" class="bucket-group">
        <strong v-if="group.currency">币种 {{ group.currency }}</strong>
        <strong v-else-if="group.unit">单位 {{ group.unit }}</strong>
        <el-table class="list-table" :data="group.rows" size="small" border>
          <el-table-column prop="label" label="值" min-width="120" />
          <el-table-column prop="value" label="数值" min-width="100" />
          <el-table-column prop="sharePercent" label="占比（服务端口径）" min-width="150">
            <template #default="{ row }">{{ row.sharePercent != null ? `${row.sharePercent}%` : '—' }}</template>
          </el-table-column>
        </el-table>
      </div>
      <p v-if="analytics.excludedReasons.length" class="hint">
        排除：{{ JSON.stringify(analytics.excludedReasons) }}
      </p>
    </section>

    <section class="lg-card panel">
      <h3>复购窗口</h3>
      <ListPageStatus :error="windowsResource.errorMessage.value" :loading="windowsResource.loading.value" :has-data="windowsResource.hasData.value" @retry="loadWindows" />
      <el-empty v-if="windowsResource.hasLoaded.value && !windowsResource.error.value && !windows.length" description="暂无可靠窗口，样本门槛与口径以当前策略为准" :image-size="60" />
      <div v-for="item in mappedWindows" :key="item.id" class="window-row">
        <strong>{{ item.productFamily }}</strong>
        <span>中位数 {{ item.medianIntervalDays ?? '—' }} 天</span>
        <span>{{ item.windowFrom }} ~ {{ item.windowTo }}</span>
        <StatusBadge size="small" :type="item.degraded ? 'warning' : 'success'">{{ item.confidenceLabel }}</StatusBadge>
        <span class="hint">非库存预测 · 可进入补货沟通窗口</span>
      </div>
    </section>
  </div>
</template>

<script setup>
import ListPageStatus from '@/components/ListPageStatus.vue'
import { useListPage } from '@/composables/useListPage'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { watchListResourceScope } from '@/composables/useListResourceScope'

import { formatMoney } from '../../../utils/money.js'

import { computed, ref, watch } from 'vue'
import { errorMessage } from '../workbenchV2Controller'
import { getOrderAnalytics, getReorderWindows, listCustomerOrders } from '@/api/customerHub'
import {
  ORDER_ANALYTICS_DIMENSIONS, ORDER_ANALYTICS_MEASURES,
  mapOrderAnalyticsBuckets, mapReorderWindow,
} from '../customerWorkspaceController'

const props = defineProps({ customerId: { type: Number, required: true }, customer: { type: Object, default: null } })
const orderState = useListPage(async ({ customerId, ...params }, { signal }) => customerId ? (await listCustomerOrders(customerId, params, { signal, suppressToast: true })).data : { items: [], total: 0 },
  { searchForm: { customerId: props.customerId }, immediate: false })
watchListResourceScope(orderState, ['customerId'])
const { list: orders, page: orderPage, pageSize: orderPageSize, total: orderTotal, loading: ordersLoading, handlePageChange, handleSizeChange, fetchList: loadOrders } = orderState
const windowsResource = useAsyncResource(async (customerId, { signal }) => (await getReorderWindows(customerId, {}, { signal, suppressToast: true })).data)
const windows = computed(() => windowsResource.data.value?.items ?? (Array.isArray(windowsResource.data.value) ? windowsResource.data.value : []))
const dimension = ref('product_family'), measure = ref('amount')
const analyticsResource = useAsyncResource(async ({ customerId, ...params }, { signal }) => (await getOrderAnalytics(customerId, params, { signal, suppressToast: true })).data)
const analytics = computed(() => mapOrderAnalyticsBuckets(analyticsResource.data.value || {}))
const mappedWindows = computed(() => windows.value.map(mapReorderWindow))
function loadAnalytics(clear = false) { return analyticsResource.load({ customerId: props.customerId, dimension: dimension.value, measure: measure.value }, { clear }) }
function loadWindows() { return windowsResource.load(props.customerId) }
function loadAll() { return Promise.all([loadOrders(), loadWindows(), loadAnalytics()]) }
watch(() => props.customerId, customerId => {
  orderState.searchForm.customerId = customerId
  orderState.handleSearch()
  windowsResource.load(customerId, { clear: true })
  loadAnalytics(true)
}, { immediate: true })

</script>

<style scoped>
.workspace-orders { display: grid; gap: 14px; }
.panel { padding: 14px 16px; }
.panel h3 { margin: 0 0 10px; font-size: 14px; }
.hint { font-size: 12px; color: var(--text-muted); font-weight: normal; }
.toolbar { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; flex-wrap: wrap; }
.bucket-group { margin-bottom: 12px; }
.window-row { display: flex; gap: 12px; align-items: center; padding: 6px 0; font-size: 13px; color: var(--text-secondary); flex-wrap: wrap; }
</style>
