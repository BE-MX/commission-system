<template>
  <div class="workspace-orders">
    <section class="lg-card panel">
      <h3>订单明细（只读）</h3>
      <el-table class="list-table" :data="orders" size="small" border>
        <el-table-column prop="order_no" label="订单号" min-width="120" show-overflow-tooltip />
        <el-table-column prop="effective_date" label="生效日" min-width="110" />
        <el-table-column prop="order_type" label="类型" min-width="80" />
        <el-table-column prop="status" label="状态" min-width="90" />
        <el-table-column label="原币金额" min-width="130">
          <template #default="{ row }">
            <span v-if="row.amount != null">{{ row.amount }} {{ row.currency || '' }}</span>
            <span v-else class="hint">未知 {{ row.amount_reason ? `(${row.amount_reason})` : '' }}</span>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <section class="lg-card panel">
      <h3>结构分析 <span class="hint">币种/单位不混加；覆盖率分母来自服务端</span></h3>
      <div class="toolbar">
        <el-select v-model="dimension" size="small" style="width: 130px" @change="loadAnalytics">
          <el-option v-for="item in ORDER_ANALYTICS_DIMENSIONS" :key="item.value" v-bind="item" />
        </el-select>
        <el-select v-model="measure" size="small" style="width: 140px" @change="loadAnalytics">
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
      <el-empty v-if="!windows.length" description="暂无可靠窗口（至少 4 个商业批次）" :image-size="60" />
      <div v-for="item in mappedWindows" :key="item.id" class="window-row">
        <strong>{{ item.productFamily }}</strong>
        <span>中位数 {{ item.medianIntervalDays ?? '—' }} 天</span>
        <span>{{ item.windowFrom }} ~ {{ item.windowTo }}</span>
        <el-tag size="small" :type="item.degraded ? 'warning' : 'success'">{{ item.confidenceLabel }}</el-tag>
        <span class="hint">非库存预测 · 可进入补货沟通窗口</span>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { getOrderAnalytics, getReorderWindows, listCustomerOrders } from '@/api/customerHub'
import {
  ORDER_ANALYTICS_DIMENSIONS, ORDER_ANALYTICS_MEASURES,
  mapOrderAnalyticsBuckets, mapReorderWindow,
} from '../customerWorkspaceController'

const props = defineProps({ customerId: { type: Number, required: true }, customer: { type: Object, default: null } })
const orders = ref([])
const windows = ref([])
const dimension = ref('product_family')
const measure = ref('amount')
const raw = ref({})
const analytics = computed(() => mapOrderAnalyticsBuckets(raw.value))
const mappedWindows = computed(() => windows.value.map(mapReorderWindow))

async function loadAll() {
  try {
    const [orderRes, windowRes] = await Promise.all([
      listCustomerOrders(props.customerId, { page: 1, page_size: 20 }),
      getReorderWindows(props.customerId, {}),
    ])
    orders.value = orderRes.data?.items ?? []
    windows.value = windowRes.data?.items ?? (Array.isArray(windowRes.data) ? windowRes.data : [])
    if (!Array.isArray(windows.value)) windows.value = []
  } catch { /* 拦截器已提示 */ }
}

async function loadAnalytics() {
  try {
    const response = await getOrderAnalytics(props.customerId, {
      dimension: dimension.value, measure: measure.value,
    })
    raw.value = response.data ?? {}
  } catch { raw.value = {} }
}

onMounted(() => { loadAll(); loadAnalytics() })
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
