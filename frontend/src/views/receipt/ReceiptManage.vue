<template>
  <div class="receipt-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="receipt-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <div class="page-header">
      <div>
        <h2>回款单</h2>
        <p>每笔回款关联订单，凭证与同步结果集中查看。</p>
      </div>
    </div>

    <el-alert class="page-alert" title="库存单完整同步后自动生成回款；失败和待核对单仍占用订单登记额度，请在原单上处理。" type="info" :closable="false" show-icon />
    <el-alert v-if="deliveryEnabled === false" class="page-alert" :title="presaleDeliveryEnabled ? '普通订单回款同步暂未启用；预售回款按预售开关独立同步。' : '小满回款同步暂未启用。已创建的回款保留在方舟，启用后自动处理。'" type="warning" :closable="false" show-icon />

    <section ref="panelRef" class="table-card receipt-panel">
      <FilterBar label="回款单筛选" :loading="loading" :pending="hasPendingSearch" :advanced-count="advancedCount" @search="handleSearch" @reset="reset">
        <el-input v-model="searchForm.keyword" clearable placeholder="回款单号 / 发票号 / 客户" aria-label="搜索回款单" class="filter-w-lg" />
        <el-input v-model="searchForm.order_id" clearable placeholder="订单 ID" aria-label="订单 ID" class="filter-w-md" />
        <el-select v-model="searchForm.sync_status" clearable placeholder="同步状态" aria-label="同步状态" class="filter-w-sm">
          <el-option v-for="s in states" :key="s" :value="s" :label="statusLabel(s)" />
        </el-select>
        <el-select v-model="searchForm.source" clearable placeholder="来源" aria-label="回款来源" class="filter-w-sm">
          <el-option label="库存单自动" value="auto" />
          <el-option label="手工登记" value="manual" />
        </el-select>
        <template #advanced>
        <el-select v-model="searchForm.status" clearable placeholder="单据状态" aria-label="单据状态" class="filter-w-sm">
          <el-option label="有效" value="active" />
          <el-option label="已作废" value="voided" />
          <el-option label="远端删除已核实" value="remote_deleted" />
        </el-select>
        <el-date-picker v-model="dates" type="daterange" value-format="YYYY-MM-DD" start-placeholder="回款开始日期" end-placeholder="结束日期" class="filter-w-lg" />
        </template>
      </FilterBar>

      <!-- 操作行：主操作按钮组 + TableTools 四图标（Action Bar Spec） -->
      <div class="action-bar">
        <GlassButton v-permission="'receipt:write'" variant="primary" left-icon="Plus" @click="batchVisible = true">新建回款单</GlassButton>
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          :loading="loading"
          @refresh="fetchList"
          @fullscreen="toggleFullscreen"
        />
      </div>

      <ListPageStatus v-if="hasData && listErrorMessage" :error="listErrorMessage" :has-data="hasData" :data-page="dataPage" @retry="fetchList" />
      <el-table v-loading="loading" :data="list" class="list-table" :class="densityClass" border :max-height="isFullscreen ? undefined : 640" @sort-change="handleTableSort" v-sticky-scrollbar>
        <template #empty>
          <ListPageStatus :error="listErrorMessage" :loading="loading || (!hasLoaded && !listErrorMessage)" @retry="fetchList">
            <el-empty :image-size="96" :description="hasActiveFilters ? '没有符合条件的记录' : '暂无数据'">
              <GlassButton v-if="hasActiveFilters" left-icon="RefreshLeft" @click="reset">重置筛选</GlassButton>
            </el-empty>
          </ListPageStatus>
        </template>
        <el-table-column v-if="visibleKeys.includes('receipt-no')" label="回款单号" min-width="240" max-width="340" show-overflow-tooltip prop="receipt_no" sortable="custom">
          <template #default="{ row }">
            <el-button link type="primary" @click="showDetail(row)"><el-icon><Document /></el-icon>{{ row.receipt_no }}</el-button>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('order-id')" prop="order_id" label="订单 ID" min-width="155" show-overflow-tooltip sortable="custom"><template #default="{ row }">{{ row.order_id || '—' }}</template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('amount')" label="本次回款金额" min-width="150" max-width="210" align="right" prop="amount" sortable="custom">
          <template #default="{ row }">{{ row.currency }} {{ money(row.amount) }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('sync-status')" label="同步状态" min-width="160" max-width="170" prop="sync_status" sortable="custom">
          <template #default="{ row }">
            <StatusBadge size="small" effect="plain" :type="statusTone(row.sync_status)">{{ row.status === 'remote_deleted' ? '远端删除已核实' : row.status === 'voided' ? '已作废' : statusLabel(row.sync_status) }}</StatusBadge>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('invoice-no')" prop="invoice_no" label="订单发票" min-width="150" max-width="210" show-overflow-tooltip sortable="custom" />
        <el-table-column v-if="visibleKeys.includes('customer')" prop="customer_name" label="客户" min-width="170" max-width="240" show-overflow-tooltip sortable="custom" />
        <el-table-column v-if="visibleKeys.includes('collection-date')" prop="collection_date" label="回款日期" min-width="130" max-width="180" sortable="custom" />
        <el-table-column v-if="visibleKeys.includes('source')" label="来源" min-width="120" max-width="170" prop="source" sortable="custom">
          <template #default="{ row }">{{ row.source === 'auto' ? '库存单自动' : '手工登记' }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('collect-status')" label="财务状态" min-width="110" max-width="160" prop="collect_status" sortable="custom">
          <template #default="{ row }">{{ financeLabel(row.collect_status) }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('attachments')" prop="attachment_count" sortable="custom" label="凭证" min-width="85" max-width="120">
          <template #default="{ row }">{{ row.attachment_count }} 张</template>
        </el-table-column>
        <el-table-column label="操作" min-width="145" max-width="300" class-name="table-action-column" fixed="right">
          <template #default="{ row }">
            <div class="table-actions">
              <el-button link type="primary" @click="showDetail(row)"><el-icon><View /></el-icon>查看</el-button>
              <el-button v-if="row.batch_id" link type="primary" @click="showBatch(row.batch_id)"><el-icon><Wallet /></el-icon>整笔回款</el-button>
              <el-button v-if="row.sync_status === 'failed' && row.status === 'active'" v-permission="'receipt:write'" link type="primary" :loading="saving" @click="retry(row)"><el-icon><Refresh /></el-icon>重试</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="page" v-model:page-size="pageSize" :total="total"
        :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next"
        class="pager" @current-change="handlePageChange" @size-change="handleSizeChange"
      />
    </section>

    <DetailDrawer v-model="editorVisible" :title="editing ? '修正回款资料' : '新建回款单'" width="640px" append-to-body destroy-on-close class="receipt-editor" :before-close="closeEditor">
      <el-form label-position="top" :model="form">
        <el-form-item v-if="!editing" label="对应订单发票" required><el-select v-model="form.invoice_id" filterable remote :remote-method="searchOrders" :loading="ordersLoading" :disabled="saving || uploading" placeholder="搜索发票号或客户" @change="selectOrder"><el-option v-for="o in orders" :key="o.id" :value="o.id" :disabled="o.sync_status !== 'synced'" :label="`${o.invoice_no} · ${o.customer_name}${o.sync_status !== 'synced' ? '（请先同步订单）' : ''}`" /></el-select></el-form-item>
        <template v-if="!editing && balance?.funding_mode === 'presale_pool'">
          <el-form-item label="收款用途" required><el-select v-model="form.purpose" :disabled="saving"><el-option value="presale_advance" label="预付货款（从本批开始抵扣）" /><el-option value="presale_deposit" label="定金（最后一批抵扣）" /></el-select></el-form-item>
          <p class="balance-hint">可用预付余额 {{ money(balance.pool_available_amount) }}；本次到账生效后余额 {{ money(remainingAfter) }}。收款可以超过当前商品明细金额。</p>
        </template>
        <template v-else-if="!editing">
          <div v-loading="balanceLoading" class="balance-card"><div>订单金额<b>{{ balance?.currency }} {{ money(balance?.total_amount) }}</b></div><div>已登记回款<b>{{ money(balance?.registered_amount) }}</b></div><div>可登记余额<b>{{ money(balance?.remaining_amount) }}</b></div></div>
          <p v-if="balance" class="balance-hint">已生效 {{ money(balance.effective_amount) }} · 登记中 {{ money(balance.pending_amount) }}；本次登记后剩余 {{ money(remainingAfter) }}</p>
        </template>
        <el-button v-if="!editing && form.invoice_id" link type="primary" @click="refreshBalance"><el-icon><Refresh /></el-icon>刷新余额（保留凭证）</el-button>
        <ReceiptFields :form="form" :readonly="saving" :currency="editing ? detail.currency : balance?.currency" show-charge @uploading="v => uploading = v" />
        <p v-if="error" class="receipt-error" role="alert">{{ error }}</p>
      </el-form>
      <template #footer><div class="dialog-footer"><GlassButton :disabled="saving || uploading" @click="closeEditor()">取消</GlassButton><GlassButton v-permission="'receipt:write'" variant="primary" :loading="saving" :disabled="uploading || (!editing && !balance)" @click="submit">{{ editing ? '保存修正' : '创建回款单' }}</GlassButton></div></template>
    </DetailDrawer>

    <BatchReceiptDialog v-if="batchVisible" @close="batchVisible = false" @saved="refreshCreate" />
    <DetailDrawer v-model="batchDetailVisible" title="整笔回款" :loading="batchLoading">
      <el-alert v-if="batchError" :title="batchError" type="error" :closable="false" />
      <template v-if="batchDetail">
        <h2>{{ batchDetail.currency }} {{ money(batchDetail.amount) }}</h2>
        <p>{{ batchDetail.collection_date }} · {{ batchDetail.payment_type }}</p>
        <el-table class="list-table" :data="batchDetail.items || batchDetail.receipts || batchDetail.allocations || []" border v-sticky-scrollbar><el-table-column prop="invoice_no" label="订单发票" /><el-table-column prop="amount" label="分配金额"><template #default="{ row }">{{ money(row.amount) }}</template></el-table-column><el-table-column label="同步状态" prop="sync_status"><template #default="{ row }">{{ statusLabel(row.sync_status) }}</template></el-table-column></el-table>
        <ReceiptProofs :model-value="batchDetail.attachments?.map(a => a.id) || batchDetail.attachment_ids || []" readonly />
      </template>
    </DetailDrawer>
    <DetailDrawer v-model="detailVisible" :title="detail?.receipt_no || '回款单详情'" :loading="!detail">
      <template v-if="detail"><div class="detail-status"><StatusBadge size="small" effect="plain" :type="statusTone(detail.sync_status)">{{ detail.status === 'voided' ? '已作废' : statusLabel(detail.sync_status) }}</StatusBadge><StatusBadge size="small" effect="plain">财务：{{ financeLabel(detail.collect_status) }}</StatusBadge></div>
        <h1 class="detail-amount">{{ detail.currency }} {{ money(detail.amount) }}</h1>
        <el-alert v-if="detail.last_error" :title="detail.last_error" type="warning" :closable="false" />
        <ResponsiveDescriptions :column="1" border class="receipt-descriptions"><el-descriptions-item label="订单发票">{{ detail.invoice_no }}</el-descriptions-item><el-descriptions-item label="客户">{{ detail.customer_name }}</el-descriptions-item><el-descriptions-item label="回款日期">{{ detail.collection_date }}</el-descriptions-item><el-descriptions-item label="回款方式">{{ detail.payment_type }}</el-descriptions-item><el-descriptions-item label="银行手续费">{{ money(detail.bank_charge) }}</el-descriptions-item><el-descriptions-item label="小满回款编号">{{ detail.xiaoman_receipt_no || '尚未取得' }}</el-descriptions-item><el-descriptions-item label="截图传输">仅方舟留存</el-descriptions-item><el-descriptions-item label="备注">{{ detail.remark || '—' }}</el-descriptions-item></ResponsiveDescriptions>
        <p>收款用途：{{ purposeLabel(detail.purpose) }}</p>
        <ReceiptPurposeCorrection :receipt="detail" :disabled="saving" @updated="row => { detail = row; refreshUpdate() }" />
        <h3>回款凭证</h3><ReceiptProofs :key="detail.id" :model-value="detail.attachments?.map(a => a.id) || []" readonly />
        <h3>同步记录</h3><el-timeline><el-timeline-item v-for="(log,i) in detail.logs" :key="i" :timestamp="formatBeijingDateTime(log.created_at)">{{ log.message }}</el-timeline-item></el-timeline>
        <el-alert v-if="candidates.length" title="以下仅为候选，管理员需核对真实凭证后绑定。" type="warning" :closable="false" /><p v-for="c in candidates" :key="c.xiaoman_receipt_id">小满 ID {{ c.xiaoman_receipt_id }} · {{ c.xiaoman_receipt_no }} · {{ money(c.amount) }}</p>
      </template>
      <template #footer><template v-if="detail"><ReceiptRemoteChange v-if="detail.status === 'active' && detail.xiaoman_receipt_id" :receipt-id="detail.id" @updated="row => { detail = row; refreshUpdate() }" /><GlassButton v-if="editable" v-permission="'receipt:write'" @click="editCurrent">修正资料</GlassButton><GlassButton v-if="editable" v-permission="'receipt:write'" @click="voidCurrent">作废</GlassButton><GlassButton v-if="detail.sync_status === 'failed' && detail.status === 'active'" v-permission="'receipt:write'" variant="primary" :loading="saving" @click="retry(detail)">重试同步</GlassButton><GlassButton v-if="['synced','uncertain'].includes(detail.sync_status)" v-any-permission="['receipt:write','receipt:admin']" :loading="saving" @click="reconcile">刷新小满结果</GlassButton><template v-if="detail.sync_status === 'uncertain' && !detail.xiaoman_receipt_id"><GlassButton v-permission="'receipt:admin'" @click="resolve('bind_receipt')">绑定已生成回款</GlassButton><GlassButton v-permission="'receipt:admin'" @click="resolve('confirm_not_created')">确认未创建</GlassButton></template></template></template>
    </DetailDrawer>
  </div>
</template>
<script setup>
import { computed, ref } from 'vue'
import BatchReceiptDialog from './BatchReceiptDialog.vue'
import { getReceiptBatch } from '@/api/receipt'
import { Document, Refresh, View } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import TableTools from '@/components/TableTools.vue'
import FilterBar from '@/components/FilterBar.vue'
import ListPageStatus from '@/components/ListPageStatus.vue'
import ReceiptFields from './ReceiptFields.vue'
import ReceiptRemoteChange from './ReceiptRemoteChange.vue'
import ReceiptPurposeCorrection from './ReceiptPurposeCorrection.vue'
import { purposeLabel } from '@/views/invoice/components/invoiceDetailLabels'
import ReceiptProofs from './ReceiptProofs.vue'
import { formatBeijingDateTime } from '@/utils/datetime'
import { useTableView } from '@/composables/useTableView'
import { useReceipts, statusLabel, statusTone, financeLabel, money } from './useReceipts'
const batchVisible = ref(false), batchDetailVisible = ref(false), batchDetail = ref(null), batchLoading = ref(false), batchError = ref('')
let batchSequence = 0
async function showBatch(id) {
  const sequence = ++batchSequence; batchDetailVisible.value = true; batchDetail.value = null; batchLoading.value = true; batchError.value = ''
  try { const data = await getReceiptBatch(id); if (sequence === batchSequence) batchDetail.value = data }
  catch (e) { if (sequence === batchSequence) batchError.value = e.message || '整笔回款加载失败' }
  finally { if (sequence === batchSequence) batchLoading.value = false }
}
const states = ['pending','syncing','synced','failed','uncertain']
const { loading,list,total,page,pageSize,searchForm,dates,fetchList,handleSearch,handleSortChange,handlePageChange,handleSizeChange,reset,
  listErrorMessage,hasLoaded,hasData,dataPage,hasPendingSearch,appliedSearchForm,refreshCreate,refreshUpdate,
  editorVisible,detailVisible,detail,saving,uploading,orders,ordersLoading,balance,balanceLoading,error,candidates,
  form,editing,selectedOrder,remainingAfter,editable,searchOrders,selectOrder,openCreate,showDetail,editCurrent,
  closeEditor,submit,retry,voidCurrent,reconcile,resolve,refreshBalance,deliveryEnabled,presaleDeliveryEnabled } = useReceipts()
const hasActiveFilters = computed(() => Object.values(appliedSearchForm.value).some(value => Array.isArray(value) ? value.length > 0 : Boolean(value)))
const advancedCount = computed(() => Number(Boolean(appliedSearchForm.value.status)) + Number(appliedSearchForm.value.dateRange?.length === 2))

// 列显隐面板数据源（TableTools；渲染保持静态模板列，v-if 按 key 控制）
const columnDefs = [
  { key: 'receipt-no', label: '回款单号' },
  { key: 'order-id', label: '订单 ID' },
  { key: 'amount', label: '本次回款金额' },
  { key: 'sync-status', label: '同步状态' },
  { key: 'invoice-no', label: '订单发票' },
  { key: 'customer', label: '客户' },
  { key: 'collection-date', label: '回款日期' },
  { key: 'source', label: '来源' },
  { key: 'collect-status', label: '财务状态' },
  { key: 'attachments', label: '凭证' },
]
// 表格视图状态（列显隐/密度/全屏）走全局基建 useTableView（Action Bar Spec）
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } =
  useTableView('receipt-manage', columnDefs)
function handleTableSort({ prop, order }) { return handleSortChange({ sort_field: order ? prop : undefined, sort_order: order === 'ascending' ? 'asc' : order === 'descending' ? 'desc' : undefined }) }
</script>
<style scoped>
.receipt-page { position: relative; }
.receipt-aurora { inset: -24px -28px; }
/* 内容压到极光之上。点名内容块，不用 > :not(.lg-aurora) 通配——
   通配会覆盖就地渲染抽屉的 .el-overlay position: fixed（DESIGN.md 红线） */
.receipt-page .page-header,
.receipt-page .page-alert,
.receipt-page .receipt-panel { position: relative; z-index: 1; }

.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; flex-wrap: wrap; margin-bottom: 16px; }
.page-header h2 { margin: 0 0 6px; font-family: var(--font-display); font-size: 17px; font-weight: 700; color: var(--text-primary); }
.page-header p { margin: 0; font-size: 14px; font-weight: 500; color: var(--text-secondary); }

.page-alert { margin-bottom: 14px; }

/* 表格面板：同款渐变玻璃（scoped 覆盖全局 .table-card 的白底） */
.receipt-panel {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
}

/* 筛选控件三档宽度、操作行、分页均为全局规范类（app.css），本页只保留玻璃皮肤覆写 */
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; padding: 14px; border-bottom: 1px solid var(--border-color); border-radius: var(--dash-card-radius) var(--dash-card-radius) 0 0; background: rgba(255, 255, 255, 0.4); }
.action-bar { background: rgba(255, 255, 255, 0.28); }

/* 全屏态：面板自身滚动 */
.receipt-panel:fullscreen { overflow: auto; }

/* 表格融进玻璃：行/表头半透明，透出极光；hover 用更实的白 */
.receipt-panel :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}

/* 右侧固定操作列磨砂不透明（Element 2.13 sticky 单元格 background: inherit 会透影，DESIGN.md） */
.receipt-panel :deep(.el-table-fixed-column--right) { background-color: rgba(249, 244, 234, 0.97); }
.receipt-panel :deep(th.el-table-fixed-column--right) { background-color: rgba(246, 239, 226, 0.98); }
.receipt-panel :deep(.el-table__body tr:hover > td.el-table-fixed-column--right) { background-color: rgba(245, 236, 220, 0.98); }

/* 抽屉内容（append-to-body 后不在 .receipt-page 下，只能用单类选择器） */
.balance-card { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; background: var(--color-gold-soft); padding: 16px; border-radius: 12px; margin: 12px 0 20px; font-size: 12px; color: var(--text-secondary); }
.balance-card b { display: block; margin-top: 8px; font-size: 16px; font-variant-numeric: tabular-nums; color: var(--text-primary); }
.balance-hint { color: var(--text-secondary); font-size: 12px; line-height: 1.8; }
.dialog-footer, .detail-status { display: flex; gap: 10px; flex-wrap: wrap; }
.dialog-footer { justify-content: flex-end; }
.receipt-error { color: var(--color-danger-text) !important; }
.receipt-descriptions { margin: 20px 0; }
.detail-amount { font-variant-numeric: tabular-nums; font-size: 28px; margin: 8px 0 12px; }
</style>
<style>
.el-drawer.receipt-editor { max-width: 100vw; }
</style>
