<template>
  <DetailDrawer :model-value="modelValue" :title="resource.data.value?.batch_no || '本地付款详情'" width="760px" :loading="resource.loading.value" @update:model-value="$emit('update:modelValue', $event)">
    <ListPageStatus :error="resource.errorMessage.value" :loading="resource.loading.value" :has-data="resource.hasData.value" :paged="false" @retry="resource.load()" />
    <template v-if="payment">
      <div class="action-bar">
        <GlassButton v-if="payment.status === 'registered'" v-permission="'receipt:admin'" variant="primary" :disabled="stale" left-icon="Check" @click="action('confirm', payment)">财务确认到账</GlassButton>
        <GlassButton v-if="payment.status === 'registered'" v-permission="'receipt:write'" :disabled="stale" left-icon="Close" @click="action('void', payment)">作废登记</GlassButton>
        <GlassButton v-if="payment.status === 'confirmed' && positive(payment.available_amount)" v-permission="'receipt:write'" variant="primary" :disabled="stale" left-icon="Money" @click="allocationOpen = true">核销应收</GlassButton>
        <GlassButton v-if="payment.status === 'confirmed' && positive(payment.available_amount)" v-permission="'receipt:admin'" :disabled="stale" left-icon="RefreshLeft" @click="action('refund', payment)">登记退款</GlassButton>
        <GlassButton left-icon="Refresh" :loading="resource.loading.value" @click="resource.load()">刷新</GlassButton>
      </div>
      <ResponsiveDescriptions :column="2" border>
        <el-descriptions-item label="客户">{{ payment.customer_name }}</el-descriptions-item><el-descriptions-item label="状态"><StatusBadge :value="payment.status" :dictionary="paymentStates" /></el-descriptions-item>
        <el-descriptions-item label="收款账户">{{ payment.account_name }}</el-descriptions-item><el-descriptions-item label="币种">{{ payment.currency }}</el-descriptions-item>
        <el-descriptions-item label="流水号">{{ payment.bank_reference }}</el-descriptions-item><el-descriptions-item label="到账日期">{{ formatBeijingDate(payment.collection_date) }}</el-descriptions-item>
        <el-descriptions-item v-for="(label, key) in moneyFields" :key="key" :label="label">{{ formatNativeMoney(payment[key]) }}</el-descriptions-item>
        <el-descriptions-item label="人民币汇率快照">{{ payment.rate_to_cny }}</el-descriptions-item><el-descriptions-item label="美元汇率快照">{{ payment.rate_to_usd }}</el-descriptions-item>
      </ResponsiveDescriptions>
      <h3>核销记录</h3>
      <el-table :data="payment.allocations || []" border class="list-table" v-sticky-scrollbar>
        <el-table-column prop="invoice_no" label="订单" min-width="155" /><el-table-column label="用途" min-width="110"><template #default="{ row }">{{ purposes[row.purpose] || row.purpose }}</template></el-table-column>
        <el-table-column label="原核销" min-width="110"><template #default="{ row }">{{ formatNativeMoney(row.amount) }}</template></el-table-column><el-table-column label="有效金额" min-width="110"><template #default="{ row }">{{ formatNativeMoney(row.effective_amount) }}</template></el-table-column><el-table-column label="已冲回" min-width="110"><template #default="{ row }">{{ formatNativeMoney(row.reversed_amount) }}</template></el-table-column><el-table-column label="有效费用" min-width="110"><template #default="{ row }">{{ formatNativeMoney(row.effective_bank_charge) }}</template></el-table-column>
        <el-table-column label="操作" min-width="100" fixed="right" class-name="table-action-column"><template #default="{ row }"><GlassButton v-if="positive(row.effective_amount)" v-permission="'receipt:admin'" variant="link" left-icon="RefreshLeft" :disabled="stale" @click="action('reverse', row)">冲回</GlassButton></template></el-table-column>
        <template #empty><el-empty description="尚无核销记录" :image-size="80" /></template>
      </el-table>
      <h3>资金事件</h3>
      <el-table :data="payment.events || []" border class="list-table" v-sticky-scrollbar><el-table-column label="业务日期" min-width="115"><template #default="{ row }">{{ formatBeijingDate(row.business_date) }}</template></el-table-column><el-table-column label="资金事件" min-width="130"><template #default="{ row }">{{ eventActions[row.action] || row.action }}</template></el-table-column><el-table-column label="金额" min-width="110"><template #default="{ row }">{{ formatNativeMoney(row.amount) }}</template></el-table-column><el-table-column label="记录时间" min-width="165"><template #default="{ row }">{{ formatBeijingDateTime(row.created_at) }}</template></el-table-column></el-table>
    </template>
  </DetailDrawer>
  <FinanceActionDialog v-model="actionOpen" :operation="operation" :target="target" @saved="saved" />
  <AllocationDialog v-model="allocationOpen" :payment="payment" @saved="saved" />
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import { getPayment } from '@/api/nativeFinance'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { formatBeijingDate, formatBeijingDateTime } from '@/utils/datetime'
import { formatNativeMoney, positive } from '../decimal'
import { paymentStates, purposes, eventActions } from '../labels'
import FinanceActionDialog from './FinanceActionDialog.vue'
import AllocationDialog from './AllocationDialog.vue'
const props = defineProps({ modelValue: Boolean, paymentId: Number }), emit = defineEmits(['update:modelValue', 'saved'])
const resource = useAsyncResource(async (id, { signal }) => (await getPayment(id, { signal, suppressToast: true })).data)
const payment = computed(() => resource.data.value), stale = computed(() => !!resource.error.value || resource.loading.value)
const moneyFields = { gross_amount: '付款总额', actual_bank_fee: '银行实际扣费', net_amount: '净到账', allocated_amount: '已核销', refunded_amount: '已退款', available_amount: '可用余额' }
const actionOpen = ref(false), allocationOpen = ref(false), operation = ref('confirm'), target = ref(null)
function action(name, row) { operation.value = name; target.value = { ...row }; actionOpen.value = true }
watch(() => [props.modelValue, props.paymentId], ([open, id]) => { if (open && id) resource.load(id, { clear: true }); else { resource.cancel(); actionOpen.value = false; allocationOpen.value = false } })
async function saved() { await resource.load(); emit('saved') }
</script>
