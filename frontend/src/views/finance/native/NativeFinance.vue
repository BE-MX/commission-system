<template>
  <div>
    <div class="page-header"><h2>本地收款与应收</h2><p>登记客户付款，由财务确认后核销订单应收；冲回和退款保留完整资金事件。</p></div>
    <div class="table-card">
      <el-tabs v-model="tab">
        <el-tab-pane label="客户付款" name="payments">
          <FilterBar :loading="payments.loading.value" @search="search" @reset="reset"><NativeCustomerPicker v-model="customerId" mode="finance" /><GlassButton v-permission="'receipt:write'" variant="primary" left-icon="Plus" @click="editorOpen = true">登记收款</GlassButton></FilterBar>
          <ListPageStatus :error="payments.errorMessage.value" :loading="payments.loading.value" :has-data="payments.hasData.value" :paged="false" @retry="payments.load()" />
          <el-table :data="payments.data.value?.items || []" v-loading="payments.loading.value" border class="list-table" v-sticky-scrollbar>
            <el-table-column prop="batch_no" label="付款单号" min-width="180"/><el-table-column prop="customer_name" label="客户" min-width="150"/><el-table-column label="状态" min-width="115"><template #default="{ row }"><StatusBadge :value="row.status" :dictionary="paymentStates" /></template></el-table-column><el-table-column prop="currency" label="币种" min-width="85"/>
            <el-table-column v-for="(label, key) in moneyFields" :key="key" :label="label" min-width="120"><template #default="{ row }">{{ formatNativeMoney(row[key]) }}</template></el-table-column><el-table-column label="到账日期" min-width="120"><template #default="{ row }">{{ formatBeijingDate(row.collection_date) }}</template></el-table-column>
            <el-table-column label="操作" min-width="95" fixed="right" class-name="table-action-column"><template #default="{ row }"><GlassButton variant="link" left-icon="View" @click="showPayment(row)">详情</GlassButton></template></el-table-column>
            <template #empty><el-empty v-if="!payments.error.value" description="暂无本地付款" :image-size="96" /></template>
          </el-table>
          <div class="pager"><GlassButton :disabled="offset === 0 || payments.loading.value" left-icon="ArrowLeft" @click="changePage(-1)">上一页</GlassButton><span>第 {{ offset / limit + 1 }} 页</span><GlassButton :disabled="payments.loading.value || !!payments.error.value || (payments.data.value?.items.length || 0) < limit" right-icon="ArrowRight" @click="changePage(1)">下一页</GlassButton></div>
        </el-tab-pane>
        <el-tab-pane label="订单应收" name="receivables"><ReceivablesPanel v-if="tab === 'receivables'" :initial-invoice="initialInvoice" /></el-tab-pane>
        <el-tab-pane label="应收账龄" name="aging">
          <template v-if="tab === 'aging'"><div class="action-bar"><GlassButton left-icon="Refresh" :loading="aging.loading.value" @click="aging.load()">刷新账龄</GlassButton><span v-if="aging.data.value">截至 {{ formatBeijingDate(aging.data.value.business_date) }}</span></div><ListPageStatus :error="aging.errorMessage.value" :loading="aging.loading.value" :has-data="aging.hasData.value" :paged="false" @retry="aging.load()" />
            <el-table :data="agingTotals" border class="list-table" v-sticky-scrollbar><el-table-column prop="currency" label="币种" min-width="85"/><el-table-column v-for="(label, key) in agingBuckets" :key="key" :label="label" min-width="130"><template #default="{ row }">{{ formatNativeMoney(row[key] || '0') }}</template></el-table-column></el-table>
            <h3>未结清应收</h3><el-table :data="aging.data.value?.items || []" border class="list-table" v-sticky-scrollbar><el-table-column prop="invoice_no" label="订单" min-width="165"/><el-table-column prop="customer_name" label="客户" min-width="140"/><el-table-column label="项目" min-width="130"><template #default="{ row }">{{ receivableKinds[row.kind] }}</template></el-table-column><el-table-column prop="currency" label="币种" min-width="85"/><el-table-column label="余额" min-width="125"><template #default="{ row }">{{ formatNativeMoney(row.remaining_amount) }}</template></el-table-column><el-table-column label="账龄" min-width="140"><template #default="{ row }">{{ agingBuckets[row.bucket] || row.bucket }}</template></el-table-column><el-table-column label="操作" fixed="right" min-width="105" class-name="table-action-column"><template #default="{ row }"><GlassButton variant="link" left-icon="View" @click="viewReceivable(row.invoice_id)">应收</GlassButton></template></el-table-column></el-table>
          </template>
        </el-tab-pane>
        <el-tab-pane v-if="canAdmin" label="资金对账" name="reconciliation">
          <template v-if="tab === 'reconciliation'"><div class="action-bar"><GlassButton left-icon="Refresh" :loading="reconciliation.loading.value" @click="reconciliation.load()">重新对账</GlassButton></div><ListPageStatus :error="reconciliation.errorMessage.value" :loading="reconciliation.loading.value" :has-data="reconciliation.hasData.value" :paged="false" @retry="reconciliation.load()" /><template v-if="reconciliation.data.value"><p>已检查 {{ reconciliation.data.value.checked_payments }} 笔付款、{{ reconciliation.data.value.checked_receivables }} 笔应收。</p><el-alert v-if="!reconciliation.data.value.differences.length" type="success" title="当前可见范围内，资金事件与余额一致" :closable="false" show-icon/><el-table v-else :data="reconciliation.data.value.differences" border class="list-table" v-sticky-scrollbar><el-table-column label="对象" min-width="145"><template #default="{ row }">{{ row.batch_id ? '付款 #' + row.batch_id : '应收 #' + row.receivable_id }}</template></el-table-column><el-table-column label="差异项" min-width="130"><template #default="{ row }">{{ reconciliationFields[row.field] || row.field }}</template></el-table-column><el-table-column prop="actual" label="当前值" min-width="125"/><el-table-column prop="expected" label="事件预期值" min-width="125"/></el-table></template></template>
        </el-tab-pane>
      </el-tabs>
    </div>
    <PaymentEditor v-model="editorOpen" @saved="created"/><PaymentDetail v-model="detailOpen" :payment-id="paymentId" @saved="payments.load()"/>
  </div>
</template>
<script setup>
import { computed, onDeactivated, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { getPayments, getFinanceAging, getFinanceReconciliation } from '@/api/nativeFinance'
import { formatBeijingDate } from '@/utils/datetime'
import NativeCustomerPicker from '@/views/invoice/native/components/NativeCustomerPicker.vue'
import PaymentEditor from './components/PaymentEditor.vue'
import PaymentDetail from './components/PaymentDetail.vue'
import ReceivablesPanel from './components/ReceivablesPanel.vue'
import { formatNativeMoney } from './decimal'
import { paymentStates, agingBuckets, receivableKinds, reconciliationFields } from './labels'
const route = useRoute(), auth = useAuthStore(), tab = ref('payments'), customerId = ref(null), appliedCustomer = ref(null), offset = ref(0), limit = 30
const canAdmin = computed(() => auth.hasPermission('receipt:admin'))
const editorOpen = ref(false), detailOpen = ref(false), paymentId = ref(null), initialInvoice = ref(null)
const moneyFields = { net_amount: '净到账', allocated_amount: '已核销', refunded_amount: '已退款', available_amount: '可用余额' }
const payments = useAsyncResource(async (params, { signal }) => (await getPayments(params, { signal, suppressToast: true })).data)
const aging = useAsyncResource(async (_, { signal }) => (await getFinanceAging({ signal, suppressToast: true })).data)
const reconciliation = useAsyncResource(async (_, { signal }) => (await getFinanceReconciliation({ signal, suppressToast: true })).data)
const agingTotals = computed(() => Object.entries(aging.data.value?.by_currency || {}).map(([currency, row]) => ({ currency, ...row })))
function loadPayments() { payments.load({ customer_id: appliedCustomer.value || undefined, offset: offset.value, limit }, { clear: true }) }
function search() { appliedCustomer.value = customerId.value; offset.value = 0; loadPayments() }
function reset() { customerId.value = null; search() }
function changePage(direction) { offset.value = Math.max(0, offset.value + direction * limit); loadPayments() }
function showPayment(row) { paymentId.value = row.id; detailOpen.value = true }
function created(row) { paymentId.value = row.id; detailOpen.value = route.path === '/finance/native'; offset.value = 0; loadPayments() }
function viewReceivable(id) { initialInvoice.value = id; tab.value = 'receivables' }
watch(tab, value => { if (value === 'aging') aging.load(); if (value === 'reconciliation' && canAdmin.value) reconciliation.load() })
watch(() => [route.path, route.query.invoice], ([path, id]) => { if (path === '/finance/native' && /^[1-9]\d*$/.test(String(id || ''))) viewReceivable(Number(id)) }, { immediate: true })
onDeactivated(() => { detailOpen.value = false; editorOpen.value = false })
loadPayments()
</script>
<style scoped>
.pager { display: flex; justify-content: flex-end; gap: var(--space-3); align-items: center; padding: var(--space-4); }
h3 { margin: var(--space-5) 0 var(--space-3); }
/* The filter is inside a tab pane rather than a direct card child. */
.table-card :deep(.filter-bar) { position: static; margin-bottom: 0; border-radius: 0; box-shadow: none; border: none; border-bottom: 1px solid var(--border-color); }
</style>
