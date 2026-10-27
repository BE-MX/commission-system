<template>
  <el-dialog v-model="visible" title="发货与收款对账" :width="'96%'" top="3vh" class="delivery-dialog"
    :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving" @closed="close">
    <div class="delivery-workspace">
      <div class="delivery-toolbar">
        <el-select v-model="customerId" filterable remote :remote-method="searchCustomers" class="delivery-control" placeholder="选择客户店名" :disabled="saving" @change="changeCustomer">
          <el-option v-for="row in customers" :key="row.id" :label="row.shop_name" :value="row.id" />
        </el-select>
        <span v-if="customer">{{ customer.settle_mode === 'credit' ? '先下单后付款 · 货款收款不改变会员等级' : '预存客户 · 本页登记交付，充值沿用客户管理' }}</span>
        <GlassButton variant="secondary" left-icon="Refresh" :loading="loading" :disabled="saving" @click="reload">刷新</GlassButton>
      </div>
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
      <el-alert v-if="summary.scope === 'own_orders'" type="info" :closable="false" title="当前仅展示本人订单的交付记录，完整客户对账由客户归属销售查看。" />
      <el-alert v-if="summary.legacy_shipped_items" type="warning" :closable="false" show-icon
        :title="`有 ${summary.legacy_shipped_items} 条历史已发明细尚无批次及收款对应关系，下方应收不包含它们，需核对期初。`" />
      <div v-if="customerId" class="delivery-summary">
        <span>未发货订单金额 <strong>{{ money(summary.unshipped_amount) }}</strong></span>
        <span>在途未结 <strong>{{ money(summary.transit_unpaid_amount) }}</strong></span>
        <span>已收货未结 <strong>{{ money(summary.received_unpaid_amount) }}</strong></span>
        <span>待核销收款 <strong>{{ money(summary.unallocated_receipts) }}</strong></span>
      </div>
      <el-tabs v-model="tab">
        <el-tab-pane label="发货批次" name="batches" />
        <el-tab-pane v-if="auth.hasAnyPermission(['domestic:write', 'domestic:admin'])" label="创建发货批次" name="create" />
        <el-tab-pane label="收款记录" name="receipts" />
      </el-tabs>
      <template v-if="tab === 'create'">
        <el-alert title="本批单价默认取订单单价，可在选择产品后修改；仅影响本批货款与收款核销，原订单价格和账户扣款保持不变。" type="info" :closable="false" />
        <div class="delivery-toolbar">
          <el-input v-model="keyword" class="delivery-control" placeholder="搜索顾客、订单号、产品规格" clearable prefix-icon="Search" />
          <el-checkbox v-model="onlySelected">只看已选</el-checkbox>
          <el-date-picker v-model="shipment.ship_time" type="datetime" value-format="YYYY-MM-DD HH:mm:ss" placeholder="发货时间" :disabled="saving" />
          <el-input v-model="shipment.remark" class="delivery-control" placeholder="批次备注（可选）" maxlength="500" :disabled="saving" />
        </div>
        <el-table :data="pageRows" row-key="item_id" border class="list-table density-compact delivery-picker" height="calc(100vh - 450px)"
          v-loading="loading" v-sticky-scrollbar @sort-change="sortTable">
          <template #empty><ListPageStatus :loading="loading" :error="error" @retry="reload"><el-empty :description="customerId ? '暂无符合条件的可发产品' : '请先选择客户'" :image-size="64" /></ListPageStatus></template>
          <el-table-column label="选择" min-width="85" :sortable="false">
            <template #default="{ row }"><input type="checkbox" class="delivery-check" :checked="!!selected[row.item_id]" :disabled="saving" :aria-label="`选择 ${row.guest_name || row.product_name}`" @change="event => toggle(row, event.target.checked)" /></template>
          </el-table-column>
          <el-table-column prop="guest_name" label="顾客名称" min-width="140" show-overflow-tooltip sortable="custom" />
          <el-table-column prop="domestic_no" label="系统订单号" min-width="175" show-overflow-tooltip sortable="custom" />
          <el-table-column prop="order_no" label="客户订单号" min-width="120" show-overflow-tooltip sortable="custom" />
          <el-table-column prop="line_code" label="明细" min-width="90" sortable="custom" />
          <el-table-column prop="product_name" label="产品规格" min-width="210" show-overflow-tooltip sortable="custom" />
          <el-table-column label="本次发" min-width="120" :sortable="false">
            <template #default="{ row }"><input type="number" class="delivery-quantity" :value="selected[row.item_id]?.quantity || 0" min="0" :max="row.available_qty" step="1" :disabled="saving" :aria-label="`${row.guest_name || row.line_code} 本次发货数量`" @change="event => { setQuantity(row, Number(event.target.value)); event.target.value = selected[row.item_id]?.quantity || 0 }" /></template>
          </el-table-column>
          <el-table-column prop="unit_price" label="订单单价" min-width="110" align="right" sortable="custom">
            <template #default="{ row }">{{ money(row.unit_price) }}</template>
          </el-table-column>
          <el-table-column label="本批单价" min-width="145" :sortable="false">
            <template #default="{ row }"><input type="number" class="delivery-money" :value="selected[row.item_id]?.unit_price ?? row.unit_price" min="0" max="999999999999.99" step="0.01" :disabled="saving || !selected[row.item_id]" :aria-label="`${row.guest_name || row.line_code} 本批单价`" :aria-invalid="selected[row.item_id] && !Number.isFinite(batchUnitPrice(row)) ? 'true' : undefined" @input="event => setUnitPrice(row, event.target.value)" /></template>
          </el-table-column>
          <el-table-column label="本次金额" min-width="110" align="right" :sortable="false">
            <template #default="{ row }">{{ money(batchUnitPrice(row) * (selected[row.item_id]?.quantity || 0)) }}</template>
          </el-table-column>
          <el-table-column prop="order_qty" label="下单" min-width="105" align="right" sortable="custom" />
          <el-table-column prop="completed_qty" label="完工" min-width="105" align="right" sortable="custom" />
          <el-table-column prop="shipped_qty" label="已发" min-width="105" align="right" sortable="custom" />
          <el-table-column prop="available_qty" label="可发" min-width="105" align="right" sortable="custom" />
          <el-table-column label="具体件号" min-width="160" class-name="table-action-column" :sortable="false">
            <template #default="{ row }"><GlassButton variant="link" left-icon="View" :disabled="saving" @click="openUnits(row)">{{ selected[row.item_id]?.unit_ids ? '已指定' : '指定件号' }}</GlassButton></template>
          </el-table-column>
        </el-table>
        <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="filtered.length" :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next" class="pager" />

      </template>
      <template v-else-if="tab === 'batches'">
        <el-table :data="batches" row-key="id" border class="list-table density-compact" height="calc(100vh - 330px)" v-loading="loading" v-sticky-scrollbar>
          <template #empty><ListPageStatus :loading="loading" :error="error" @retry="reload"><el-empty description="暂无发货批次" :image-size="64" /></ListPageStatus></template>
          <el-table-column type="expand">
            <template #default="{ row }">
              <el-table :data="row.items" border class="list-table density-compact" v-sticky-scrollbar>
                <el-table-column prop="guest_name" label="顾客名称" min-width="140" show-overflow-tooltip sortable />
                <el-table-column prop="domestic_no" label="系统订单号" min-width="175" sortable />
                <el-table-column prop="order_no" label="客户订单号" min-width="120" show-overflow-tooltip sortable />
                <el-table-column prop="line_code" label="明细" min-width="90" sortable />
                <el-table-column prop="product_name" label="产品规格" min-width="210" show-overflow-tooltip sortable />
                <el-table-column prop="quantity" label="发货数量" min-width="95" align="right" sortable />
                <el-table-column prop="unit_price" label="本批单价" min-width="110" align="right" sortable><template #default="{ row: item }">{{ money(item.unit_price) }}</template></el-table-column>
                <el-table-column prop="amount" label="金额" min-width="110" align="right" sortable><template #default="{ row: item }">{{ money(item.amount) }}</template></el-table-column>
                <el-table-column label="具体件号" min-width="200" show-overflow-tooltip :sortable="false"><template #default="{ row: item }">{{ item.unit_codes.join('、') }}</template></el-table-column>
              </el-table>
            </template>
          </el-table-column>
          <el-table-column prop="shipment_no" label="批次号" min-width="235" sortable />
          <el-table-column prop="ship_time" label="发货时间" min-width="175" sortable />
          <el-table-column prop="received_date" label="收货日期" min-width="110" sortable />
          <el-table-column prop="total_amount" label="批次金额" min-width="110" align="right" sortable><template #default="{ row }">{{ money(row.total_amount) }}</template></el-table-column>
          <el-table-column prop="paid_amount" label="已核销" min-width="110" align="right" sortable><template #default="{ row }">{{ money(row.paid_amount) }}</template></el-table-column>
          <el-table-column prop="unpaid_amount" label="未结" min-width="110" align="right" sortable><template #default="{ row }">{{ money(row.unpaid_amount) }}</template></el-table-column>
          <el-table-column label="操作" min-width="340" class-name="table-action-column">
            <template #default="{ row }">
              <StatusBadge v-if="row.cancelled_at" label="已取消" size="small" />
              <GlassButton v-if="!row.cancelled_at && !row.received_date && row.created_by === auth.user?.id" v-permission="'domestic:write'" variant="link" left-icon="Check" :disabled="saving" @click="openReceive(row)">确认收货</GlassButton>
              <GlassButton v-if="!row.cancelled_at && canFunds && customer?.settle_mode === 'credit' && row.unpaid_amount > 0" v-any-permission="['domestic:recharge', 'domestic:admin']" variant="link" left-icon="Wallet" :disabled="saving" @click="openReceipt(row)">登记收款</GlassButton>
              <GlassButton variant="link" left-icon="Download" @click="exportBatch(row)">导出清单</GlassButton>
              <GlassButton v-if="!row.cancelled_at && !row.received_date && row.created_by === auth.user?.id" v-any-permission="['domestic:write', 'domestic:admin']" variant="link" link-tone="danger" left-icon="Close" :disabled="saving || loading || !!error" @click="cancelBatch(row)">取消批次</GlassButton>
            </template>
          </el-table-column>
        </el-table>
      </template>
      <template v-else>
        <div class="delivery-toolbar">
          <GlassButton v-if="canFunds && customer?.settle_mode === 'credit'" v-any-permission="['domestic:recharge', 'domestic:admin']" variant="primary" left-icon="Wallet" :disabled="saving || loading || !!error" @click="openReceipt()">登记收款</GlassButton>
          <span>待审核款不计入已收款；可先登记收款，再核销到批次。</span>
        </div>
        <el-table :data="receipts" row-key="id" border class="list-table density-compact" v-loading="loading" v-sticky-scrollbar>
          <template #empty><ListPageStatus :loading="loading" :error="error" @retry="reload"><el-empty description="暂无货款收款记录" :image-size="64" /></ListPageStatus></template>
          <el-table-column prop="id" label="申请编号" min-width="95" sortable />
          <el-table-column prop="receipt_date" label="收款日期" min-width="110" sortable />
          <el-table-column prop="amount" label="收款金额" min-width="110" align="right" sortable><template #default="{ row }">{{ money(row.amount) }}</template></el-table-column>
          <el-table-column prop="status" label="审核状态" min-width="100" sortable><template #default="{ row }">{{ statusLabel[row.status] || row.status }}</template></el-table-column>
          <el-table-column label="对应批次" min-width="260" show-overflow-tooltip :sortable="false"><template #default="{ row }">{{ row.allocations.map(a => a.shipment_no + '：' + money(a.amount)).join('；') || '待核销' }}</template></el-table-column>
          <el-table-column prop="unallocated_amount" label="未核销金额" min-width="120" align="right" sortable><template #default="{ row }">{{ money(row.unallocated_amount) }}</template></el-table-column>
          <el-table-column label="操作" min-width="140" class-name="table-action-column"><template #default="{ row }"><GlassButton v-if="canFunds && row.status === 'approved' && row.unallocated_amount > 0" v-any-permission="['domestic:recharge', 'domestic:admin']" variant="link" left-icon="Tickets" @click="openReceipt(null, row)">核销到批次</GlassButton></template></el-table-column>
        </el-table>
      </template>
    </div>
    <template v-if="tab === 'create'" #footer>
        <div class="delivery-footer">
          <strong>已选 {{ totals.lines }} 条 · {{ totals.quantity }} 件 · {{ money(totals.cents / 100) }}</strong>
          <span>未指定件号时按可发件号顺序选取；搜索和翻页保留选择。</span>
          <GlassButton v-permission="'domestic:write'" variant="primary" left-icon="Van" :loading="saving"
            :disabled="!totals.quantity || loading || !!error" @click="submitShipment">登记发货批次</GlassButton>
        </div>
    </template>
  </el-dialog>
  <el-dialog v-model="units.visible" :title="`${units.row?.guest_name || ''} · ${units.row?.line_code || ''} · 指定实际发货件号`" width="640px" :close-on-click-modal="false">
    <el-input v-model="units.keyword" placeholder="查找件号；扫码或输入 A1-01 后按回车选中" clearable @keyup.enter="scanUnit" />
    <el-checkbox-group v-model="units.selected" class="delivery-unit-options">
      <el-checkbox v-for="row in unitOptions" :key="row.id" :label="row.id">{{ row.code }}</el-checkbox>
    </el-checkbox-group>
    <template #footer><span>已选 {{ units.selected.length }} 件</span><GlassButton variant="primary" left-icon="Check" @click="confirmUnits">使用这些件号</GlassButton></template>
  </el-dialog>
  <el-dialog v-model="receive.visible" title="确认客户收货" width="480px" :show-close="!saving" :close-on-click-modal="false">
    <p>{{ receive.row?.shipment_no }}</p>
    <el-date-picker v-model="receive.date" type="date" value-format="YYYY-MM-DD" placeholder="收货日期" :disabled="saving" />
    <template #footer><GlassButton variant="primary" left-icon="Check" :loading="saving" @click="confirmReceive">确认收货</GlassButton></template>
  </el-dialog>
  <el-dialog v-model="receipt.visible" :title="receipt.existing ? '核销已入账货款' : '登记货款收款（提交审核）'" width="760px" :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving">
    <el-form label-position="top" :disabled="saving">
      <div class="delivery-receipt-fields">
        <el-form-item label="本次金额"><el-input-number v-model="receipt.amount" :precision="2" :min="0.01" :disabled="!!receipt.existing" /></el-form-item>
        <el-form-item v-if="!receipt.existing" label="实际收款日期"><el-date-picker v-model="receipt.date" type="date" value-format="YYYY-MM-DD" /></el-form-item>
      </div>
      <el-form-item v-if="!receipt.existing" label="转账凭证"><AppUpload v-model="receipt.files" accept="image/jpeg,image/png,image/webp,application/pdf" :limit="1" :upload-fn="selectVoucher" :disabled="saving" /></el-form-item>
      <el-form-item v-if="!receipt.existing" label="说明"><el-input v-model="receipt.remark" maxlength="500" /></el-form-item>
      <p>填写本次要核销的批次金额；可跨批次，也可保留未核销金额。</p>
      <el-table :data="openBatches" row-key="id" border class="list-table density-compact" max-height="280" v-sticky-scrollbar>
        <el-table-column prop="shipment_no" label="发货批次" min-width="235" sortable />
        <el-table-column prop="unpaid_amount" label="未结金额" min-width="110" align="right" sortable><template #default="{ row }">{{ money(row.unpaid_amount) }}</template></el-table-column>
        <el-table-column :label="receipt.existing ? '累计核销' : '本次核销'" min-width="155" :sortable="false"><template #default="{ row }"><input type="number" class="delivery-money" :value="receipt.allocations[row.id] || 0" :min="previousAllocation(row.id)" :max="row.unpaid_amount + previousAllocation(row.id)" step="0.01" :aria-label="`${row.shipment_no} 核销金额`" :disabled="saving" @change="event => { setAllocation(row, Number(event.target.value)); event.target.value = receipt.allocations[row.id] || 0 }" /></template></el-table-column>
      </el-table>
    </el-form>
    <template #footer><span>核销 {{ money(allocationTotal) }} · 剩余 {{ money(receipt.amount - allocationTotal) }}</span><GlassButton variant="primary" left-icon="Check" :loading="saving" @click="confirmReceipt">{{ receipt.existing ? '保存核销' : '提交收款审核' }}</GlassButton></template>
  </el-dialog>
</template>

<script setup>
import { watch, computed } from 'vue'
import AppUpload from '@/components/AppUpload.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { useAuthStore } from '@/stores/auth'
import { formatMoney } from '@/utils/money'
import { downloadBlob } from '@/utils/download'
import { useDomesticDelivery } from '../composables/useDomesticDelivery'
const emit = defineEmits(['changed'])
const auth = useAuthStore()
const { visible, loading, saving, error, customers, customerId, customer, batches, receipts, summary, tab,
  keyword, selected, onlySelected, page, pageSize, sort, shipment, units, receive, receipt, totals, filtered, pageRows,
  openBatches, allocationTotal, unitOptions, open, searchCustomers, close, changeCustomer, reload, setQuantity, setUnitPrice, batchUnitPrice, toggle, openUnits,
  confirmUnits, scanUnit, submitShipment, cancelBatch, openReceive, confirmReceive, openReceipt, selectVoucher, setAllocation, confirmReceipt } = useDomesticDelivery(emit)
const money = value => Number.isFinite(Number(value ?? 0)) ? formatMoney(Number(value ?? 0), { currency: 'CNY', currencyDisplay: 'narrowSymbol' }) : '待填写有效单价'
const canFunds = computed(() => customer.value?.can_operate_funds ?? (customer.value?.owner_user_id === auth.user?.id || (auth.user?.roles || []).includes('super_admin')))
const previousAllocation = id => receipt.existing?.allocations.find(row => row.shipment_id === id)?.amount || 0
const statusLabel = { pending: '待审核', approved: '已通过', rejected: '已驳回', withdrawn: '已撤回' }
watch([keyword, onlySelected, pageSize], () => { page.value = 1 })
function sortTable({ prop, order }) { Object.assign(sort, { prop, order }); page.value = 1 }
function exportBatch(batch) {
  const rows = [['批次号', '顾客名称', '系统订单号', '客户订单号', '明细', '产品规格', '数量', '单价', '金额', '具体件号'],
    ...batch.items.map(row => [batch.shipment_no, row.guest_name, row.domestic_no, row.order_no, row.line_code,
      row.product_name, row.quantity, row.unit_price, row.amount, row.unit_codes.join('、')])]
  const quote = value => '"' + String(value ?? '').replace(/^[=+@-]/, "'$&").replaceAll('"', '""') + '"'
  downloadBlob({ data: new Blob(['\ufeff' + rows.map(row => row.map(quote).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8' }) }, batch.shipment_no + '.csv')
}
defineExpose({ open })
</script>

<style scoped>
.delivery-workspace { min-height: 65vh; }
.delivery-toolbar, .delivery-footer, .delivery-summary { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
.delivery-control { max-width: 280px; }
.delivery-toolbar > span, .delivery-footer > span { color: var(--text-secondary); font-size: 13px; }
.delivery-summary { padding: 10px 12px; background: var(--page-bg); border-radius: 8px; }
.delivery-summary > span { margin-right: 12px; }
.delivery-footer { width: 100%; margin-bottom: 0; justify-content: space-between; }
.delivery-picker { --table-cell-padding-compact: 4px; }
.delivery-quantity { width: 85px; height: 24px; box-sizing: border-box; padding: 0 6px; border: 1px solid var(--border-color); border-radius: 4px; color: var(--text-primary); background: var(--page-bg); font: inherit; }
.delivery-money { width: 115px; height: 28px; box-sizing: border-box; border: 1px solid var(--border-color); border-radius: 4px; padding: 0 6px; color: var(--text-primary); background: var(--page-bg); font: inherit; }
.delivery-money[aria-invalid="true"] { border-color: var(--color-danger); }
.delivery-money:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 1px; }
.delivery-check { width: 16px; height: 16px; vertical-align: middle; accent-color: var(--color-primary); }
.delivery-unit-options { display: flex; flex-wrap: wrap; gap: 8px 16px; max-height: 50vh; overflow: auto; margin-top: 16px; }
.delivery-receipt-fields { display: flex; gap: 24px; flex-wrap: wrap; }
@media (pointer: coarse) {
  .delivery-picker { --table-cell-padding-compact: 10px; }
  .delivery-quantity, .delivery-check, .delivery-money { min-height: 44px; }
}
</style>
