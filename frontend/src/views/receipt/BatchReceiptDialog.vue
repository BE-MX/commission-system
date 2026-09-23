<template>
  <el-dialog :model-value="true" title="新建回款单 · 分配订单" width="860px" append-to-body :before-close="close" :close-on-click-modal="false">
    <el-form label-position="top" :disabled="saving">
      <el-form-item label="选择订单" required>
        <el-select v-model="selectedId" filterable remote :remote-method="search" :loading="searching" placeholder="搜索发票号或客户，首单确定客户和币种" @change="addOrder">
          <el-option v-for="order in options" :key="order.id" :value="order.id" :label="`${order.invoice_no} · ${order.customer_name} · ${order.currency}`" :disabled="order.sync_status !== 'synced' || rows.some(r => r.id === order.id)" />
        </el-select>
      </el-form-item>
      <p v-if="rows.length">{{ rows[0].customer_name }} · {{ rows[0].currency }}；同一笔凭证仅上传一次，按下表金额分配。</p>
      <el-table class="list-table" :data="rows" border>
        <el-table-column prop="invoice_no" label="订单发票" min-width="150" />
        <el-table-column label="可登记余额" min-width="130"><template #default="{ row }">{{ row.balance ? money(row.balance.remaining_amount) : '未核验' }}</template></el-table-column>
        <el-table-column label="本次分配" min-width="185"><template #default="{ row }"><el-input-number v-model="row.amount" :min="0.01" :precision="2" controls-position="right" /></template></el-table-column>
        <el-table-column label="操作" min-width="120"><template #default="{ row }"><el-button link :loading="row.loading" @click="refresh(row)">刷新</el-button><el-button link @click="remove(row)">移除</el-button></template></el-table-column>
      </el-table>
      <p>分配合计：{{ allocatedTotal }} {{ rows[0]?.currency }}</p>
      <ReceiptFields :form="form" :currency="rows[0]?.currency" :readonly="saving" show-charge @uploading="v => uploading = v" />
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
    </el-form>
    <template #footer><GlassButton :disabled="saving || uploading" @click="close()">取消</GlassButton><GlassButton v-permission="'receipt:write'" variant="primary" :loading="saving" :disabled="uploading || rows.some(r => r.loading)" @click="submit">创建回款单</GlassButton></template>
  </el-dialog>
</template>
<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import GlassButton from '@/components/GlassButton.vue'
import ReceiptFields from './ReceiptFields.vue'
import { getReceiptOrders, getReceiptBalance, createReceiptBatch } from '@/api/receipt'
import { currentBeijingDate } from '@/utils/datetime'
import { msgSuccess } from '@/utils/feedback'
import { cents, validateAllocations, latestRequest } from './batchReceiptState'
import { money } from './useReceipts'
const emit = defineEmits(['close', 'saved'])
const rows = ref([]), options = ref([]), selectedId = ref(null), searching = ref(false), saving = ref(false), uploading = ref(false), error = ref('')
const form = reactive({ amount: null, collection_date: currentBeijingDate(), payment_type: '', bank_charge: 0, attachment_ids: [], remark: '' })
const requestKey = crypto.randomUUID(), searchRequest = latestRequest()
const allocatedTotal = computed(() => (rows.value.reduce((sum, row) => sum + (cents(row.amount) || 0), 0) / 100).toFixed(2))
async function search(keyword = '') {
  const sequence = searchRequest.next(); searching.value = true
  try {
    const first = rows.value[0]
    const data = await getReceiptOrders({ keyword, customer_id: first?.customer_id, currency: first?.currency })
    if (searchRequest.isCurrent(sequence)) options.value = data.items
  } catch { if (searchRequest.isCurrent(sequence)) error.value = '订单加载失败，请重新搜索' }
  finally { if (searchRequest.isCurrent(sequence)) searching.value = false }
}
async function refresh(row) {
  if (row.loading) return
  row.loading = true; row.balance = null
  try { row.balance = await getReceiptBalance(row.id) }
  catch { error.value = '余额核验失败，金额和凭证已保留，请刷新重试' }
  finally { row.loading = false }
}
async function addOrder(id) {
  const order = options.value.find(row => row.id === id); selectedId.value = null
  if (!order || rows.value.some(row => row.id === id)) return
  const first = rows.value[0]
  if (first && (first.customer_id !== order.customer_id || first.currency !== order.currency)) { error.value = '请选择同一客户、同一币种订单'; return }
  const row = reactive({ ...order, amount: null, balance: null, loading: false }); rows.value.push(row)
  await Promise.all([refresh(row), search()])
}
function remove(row) { rows.value = rows.value.filter(r => r.id !== row.id); search() }
async function close(done) {
  if (saving.value || uploading.value) return
  if (rows.value.length || form.amount || form.attachment_ids.length) {
    try { await ElMessageBox.confirm('尚未提交的回款信息将被丢弃，确定关闭？', '关闭回款单', { type: 'warning' }) } catch { return }
  }
  searchRequest.next(); emit('close'); if (typeof done === 'function') done()
}
async function submit() {
  if (saving.value || uploading.value || rows.value.some(r => r.loading)) return
  error.value = validateAllocations(rows.value, form.amount)
  if (!error.value && (!form.collection_date || !form.payment_type || !form.attachment_ids.length)) error.value = '请填写回款日期、方式并上传凭证'
  if (error.value) return
  saving.value = true
  try {
    const result = await createReceiptBatch({ ...form, amount: String(form.amount), bank_charge: String(form.bank_charge || 0), attachment_ids: [...form.attachment_ids], request_key: requestKey,
      allocations: rows.value.map(row => ({ invoice_id: row.id, settlement_id: row.balance.settlement_id || null, amount: String(row.amount), balance_version: row.balance.version })) })
    msgSuccess('回款已创建，等待同步处理'); emit('saved', result); emit('close')
  } catch (e) { error.value = e.response?.data?.detail || e.message || '保存失败，资料已保留，请重试' }
  finally { saving.value = false }
}
onMounted(() => search())
</script>
