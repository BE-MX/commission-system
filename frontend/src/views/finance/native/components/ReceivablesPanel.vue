<template>
  <div>
    <div class="action-bar"><NativeOrderPicker v-model="invoiceId" :initial-option="resource.data.value?.invoice" /><GlassButton :disabled="!invoiceId" :loading="resource.loading.value" left-icon="Refresh" @click="resource.load()">刷新应收</GlassButton></div>
    <ListPageStatus :error="resource.errorMessage.value" :loading="resource.loading.value" :has-data="resource.hasData.value" :paged="false" @retry="resource.load()" />
    <template v-if="resource.data.value">
      <p>{{ resource.data.value.invoice.invoice_no }} · {{ resource.data.value.invoice.customer_name }} · {{ resource.data.value.invoice.currency }}</p>
      <el-table :data="resource.data.value.items" border class="list-table" v-sticky-scrollbar>
        <el-table-column label="应收项目" min-width="145"><template #default="{ row }">{{ receivableKinds[row.kind] }}<span v-if="row.settlement_id"> · 批次 #{{ row.settlement_id }}</span></template></el-table-column>
        <el-table-column v-for="(label, key) in moneyFields" :key="key" :label="label" min-width="115"><template #default="{ row }">{{ formatNativeMoney(row[key]) }}</template></el-table-column>
        <el-table-column label="到期日" min-width="120"><template #default="{ row }">{{ row.due_date ? formatBeijingDate(row.due_date) : '未设置' }}</template></el-table-column>
        <el-table-column label="操作" min-width="175" fixed="right" class-name="table-action-column"><template #default="{ row }"><template v-if="!row.cancelled"><GlassButton v-permission="'receipt:admin'" variant="link" left-icon="Edit" :disabled="resource.loading.value || !!resource.error.value" @click="action('adjust', row)">调整</GlassButton><GlassButton v-permission="'receipt:admin'" variant="link" left-icon="Calendar" :disabled="resource.loading.value || !!resource.error.value" @click="action('due', row)">到期日</GlassButton></template></template></el-table-column>
        <template #empty><el-empty description="该订单暂无应收，请先确认订单" :image-size="96" /></template>
      </el-table>
    </template>
    <el-empty v-else-if="!resource.loading.value && !resource.error.value" description="选择本地订单查看应收" :image-size="96" />
    <FinanceActionDialog v-model="actionOpen" :operation="operation" :target="target" @saved="resource.load()" />
  </div>
</template>
<script setup>
import { onDeactivated, ref, watch } from 'vue'
import { getReceivables } from '@/api/nativeFinance'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { formatBeijingDate } from '@/utils/datetime'
import { formatNativeMoney } from '../decimal'
import { receivableKinds } from '../labels'
import NativeOrderPicker from './NativeOrderPicker.vue'
import FinanceActionDialog from './FinanceActionDialog.vue'
const props = defineProps({ initialInvoice: Number })
const invoiceId = ref(null), actionOpen = ref(false), operation = ref('adjust'), target = ref(null)
onDeactivated(() => { actionOpen.value = false })
const moneyFields = { amount: '原始应收', adjustment_amount: '累计调整', paid_amount: '已核销', remaining_amount: '应收余额' }
const resource = useAsyncResource(async (id, { signal }) => (await getReceivables(id, { signal, suppressToast: true })).data)
watch(() => props.initialInvoice, id => { invoiceId.value = id || null }, { immediate: true })
watch(invoiceId, id => { resource.clear(); if (id) resource.load(id) }, { immediate: true })
function action(name, row) { operation.value = name; target.value = { ...row, invoice_id: invoiceId.value, invoice_no: resource.data.value.invoice.invoice_no }; actionOpen.value = true }
</script>
