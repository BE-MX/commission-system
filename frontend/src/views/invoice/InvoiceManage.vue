<template>
  <div class="invoice-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="invoice-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <div class="page-header">
      <div>
        <h2>订单发票管理</h2>
        <p>客户发票、产品明细、价格管控、导出与小满同步集中处理。</p>
      </div>
    </div>

    <el-alert v-if="!shipmentCapabilities.enabled" :title="shipmentCapabilities.reason || '预售出库暂未启用'" type="info" :closable="false" />
    <InvoiceOverview
      v-model:date-range="summaryDateRange"
      :summary="summary"
      :loading="summaryLoading"
      :error="summaryError"
      :money="money"
      @range-change="loadSummary"
    />

    <section ref="panelRef" class="table-card invoice-panel">
      <FilterBar label="发票筛选" :loading="loading" :pending="hasPendingSearch" @search="handleSearch" @reset="resetFilters">
        <el-input
          v-model="filters.keyword"
          clearable
          placeholder="搜索发票号/客户"
          class="filter-w-lg"
          aria-label="搜索发票"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-input v-model="filters.order_id" clearable placeholder="订单 ID" aria-label="订单 ID" class="filter-w-md" />
        <el-select v-model="filters.order_type" clearable placeholder="订单类型" aria-label="订单类型" class="filter-w-sm">
          <el-option label="库存单" value="stock" />
          <el-option label="生产单" value="production" />
          <el-option label="预售单" value="presale" />
        </el-select>
        <el-select v-model="filters.status" clearable placeholder="状态" aria-label="发票状态" class="filter-w-sm">
          <el-option v-for="option in statusOptions" :key="option.value" :label="option.label" :value="option.value" />
        </el-select>
      </FilterBar>

      <!-- 操作行：主操作按钮组 + TableTools 四图标（Action Bar Spec） -->
      <div class="action-bar">
        <GlassButton v-permission="'invoice:write'" variant="primary" :left-icon="Box" @click="openCreate('stock')">新建库存单</GlassButton>
        <GlassButton v-permission="'invoice:write'" variant="secondary" :left-icon="Tools" @click="openCreate('production')">新建生产单</GlassButton>
        <GlassButton v-permission="'invoice:write'" variant="secondary" :left-icon="Calendar" :disabled="!shipmentCapabilities.enabled" @click="openCreate('presale')">新建预售单</GlassButton>
        <!-- 旧版下单入口（过渡期）：新版为默认，旧版布局给习惯老流程的同事 -->
        <el-dropdown v-permission="'invoice:write'" trigger="click" @command="openLegacyCreate">
          <GlassButton variant="secondary">
            旧版入口<el-icon><ArrowDown /></el-icon>
          </GlassButton>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="stock">库存单（旧版）</el-dropdown-item>
              <el-dropdown-item command="production">生产单（旧版）</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          :loading="loading"
          @refresh="loadInvoices"
          @fullscreen="toggleFullscreen"
        />
      </div>

      <ListPageStatus v-if="hasData && listErrorMessage" :error="listErrorMessage" :has-data="hasData" :data-page="dataPage" @retry="loadInvoices" />
      <el-table v-loading="loading" :data="invoices" @sort-change="handleTableSort" border class="list-table invoice-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640">
        <template #empty>
          <ListPageStatus :error="listErrorMessage" :loading="loading || (!hasLoaded && !listErrorMessage)" @retry="loadInvoices">
            <el-empty :image-size="96" :description="hasActiveFilters ? '没有符合条件的发票' : '暂无发票，新建一张发票后会显示在这里'">
              <GlassButton v-if="hasActiveFilters" :left-icon="RefreshLeft" @click="resetFilters">重置筛选</GlassButton>
            </el-empty>
          </ListPageStatus>
        </template>
        <el-table-column
          v-for="column in visibleColumns"
          :key="column.key"
          :prop="column.prop || (column.key === 'created_by' ? 'created_by_name' : column.key)" sortable="custom"
          :label="column.label"
          :min-width="column.minWidth"
          :max-width="column.maxWidth"
          :align="column.align"
          :class-name="column.className"
          :show-overflow-tooltip="Boolean(column.tooltip)"
        >
          <template #default="{ row }">
            <span v-if="column.key === 'invoice_no'" class="invoice-number">{{ row.invoice_no }}</span>
            <StatusBadge v-else-if="column.key === 'order_type'" size="small" :type="orderTypeTone(row.order_type)" effect="plain">{{ orderTypeLabel(row.order_type) }}</StatusBadge>
            <template v-else-if="column.key === 'total_amount'">{{ row.currency === 'USD' ? '' : `${row.currency} ` }}{{ money(row.total_amount) }}</template>
            <StatusBadge v-else-if="column.key === 'status'" size="small" :type="statusType(row.status)" effect="plain">{{ statusText(row.status) }}</StatusBadge>
            <StatusBadge v-else-if="column.key === 'sync_status'" size="small" :type="syncType(row.sync_status)" effect="plain">{{ syncText(row.sync_status) }}</StatusBadge>
            <template v-else-if="column.key === 'created_by'">{{ row.created_by_name || '-' }}</template>
            <template v-else-if="column.key === 'created_at'">{{ formatDateTime(row.created_at) }}</template>
            <template v-else>{{ row[column.prop] }}</template>
          </template>
        </el-table-column>
        <el-table-column class-name="table-action-column" label="操作" min-width="300" max-width="360" fixed="right">
          <template #default="{ row }">
            <div class="table-actions">
              <el-button v-permission="'invoice:write'" link type="primary" :disabled="['cancel_pending','cancelled'].includes(row.status)" @click="openEdit(row.id)">
                <el-icon><Edit /></el-icon>
                编辑
              </el-button>
              <el-button
                v-permission="'invoice:sync'"
                link
                type="warning"
                :loading="isInvoiceSyncing(row.id)"
                :disabled="['cancel_pending','cancelled'].includes(row.status)"
                @click="validateAndSync(row.id)"
              >
                <el-icon><Refresh /></el-icon>
                {{ isInvoiceSyncing(row.id) ? '同步中' : '同步' }}
              </el-button>
              <el-dropdown
                v-if="row.sync_status === 'sync_uncertain'"
                v-permission="'invoice:admin'"
                trigger="click"
                @command="command => resolveUncertain(row, command)"
              >
                <el-button link type="danger"><el-icon><Check /></el-icon>处理待核对</el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item v-if="!row.xiaoman_order_id" command="bind_order">绑定已生成订单</el-dropdown-item>
                    <el-dropdown-item v-if="!row.xiaoman_order_id" command="confirm_not_created">确认未生成并允许重试</el-dropdown-item>
                    <el-dropdown-item v-if="row.xiaoman_order_id" command="confirm_existing">核实原订单更新结果</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
              <el-button v-if="row.order_type === 'presale'" v-permission="'shipment:write'" link type="primary" :disabled="!shipmentCapabilities.enabled || row.sync_status !== 'synced' || ['cancel_pending','cancelled'].includes(row.status)" @click="shipmentInvoice = row"><el-icon><Box /></el-icon>生成出库单</el-button>
              <el-dropdown trigger="click" placement="bottom-end">
                <el-button link>更多<el-icon><ArrowDown /></el-icon></el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item :icon="Download" @click="handleExport('excel', row)">导出 Excel</el-dropdown-item>
                    <el-dropdown-item :icon="Download" @click="handleExport('pdf', row)">导出 PDF</el-dropdown-item>
                    <el-dropdown-item :icon="Download" @click="handleExport('print', row)">打印 / 预览</el-dropdown-item>
                    <div v-permission="'invoice:read'" role="none">
                      <el-dropdown-item :icon="Document" @click="openSyncLogs(row)">日志</el-dropdown-item>
                    </div>
                    <div v-permission="'invoice:admin'" role="none">
                      <el-dropdown-item @click="openLifecycle(row)">取消 / 恢复</el-dropdown-item>
                    </div>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
              <el-button v-if="!row.xiaoman_order_id && !['cancel_pending','cancelled'].includes(row.status)" v-permission="'invoice:write'" link type="danger" @click="removeInvoice(row)">
                <el-icon><Delete /></el-icon>
                删除
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        class="pager"
        @size-change="handleSizeChange"
        @current-change="handlePageChange"
      />
    </section>

    <el-drawer v-model="drawerVisible" :title="drawerTitle" size="94%"
               body-class="invoice-modern-drawer-body" footer-class="invoice-modern-drawer-footer">
      <template #default>
        <el-form label-position="top" ref="formRef" :model="form" class="invoice-form">
          <div class="drawer-panes">
            <!-- 左窗格：录入主流（客户/订单 → 产品明细 → 配件明细），独立滚动 -->
            <main class="pane pane-main">
              <LinkedSyncResult
                :operation="linkedOperation"
                :busy="linkedBusy"
                @refresh="refreshLinked"
                @retry="retryLinked"
                @recheck="recheckLinked"
                @close="closeLinked"
                @resolve="resolveLinked"
              />
              <InvoiceOrderCustomerFields
                v-model:selected-customer="selectedCustomer"
                v-model:private-only-company="privateOnlyCompany"
                :form="form" :sales-user-options="salesUserOptions" :customer-options="customerOptions"
                :customer-loading="customerLoading" :customer-total="customerTotal"
                :customer-has-more="customerHasMore" :okki-bound="okkiBound"
                :can-toggle-private="canTogglePrivate" :customer-rule="customerRule"
                :last-order-date="lastOrderDate" :invoice-no-taken="invoiceNoTaken"
                :previous-invoice-no="previousInvoiceNo" :on-sales-user-change="onSalesUserChange"
                :search-customers="searchCustomers" :on-customer-change="onCustomerChange"
                :load-more-customers="loadMoreCustomers" :select-synced-customer="selectSyncedCustomer"
                :mark-customer-grade-touched="markCustomerGradeTouched"
                :on-invoice-no-input="onInvoiceNoInput" :on-invoice-no-blur="onInvoiceNoBlur"
                :on-currency-change="onCurrencyChange" :mark-okki-flag-touched="markOkkiFlagTouched"
                @open-whole-order-paste="wholeOrderPasteVisible = true"
              />

              <InvoiceHairTable
                class="form-card"
                :items="hairItems"
                :is-production="isProduction"
                :entry-options="entryOptions"
                :can-paste-import="canPasteImport"
                :paste-import-disabled-reason="pasteImportDisabledReason"
                :load-line-options="loadLineOptions"
                :on-line-filter-change="onLineFilterChange"
                :on-custom-field-change="onCustomFieldChange"
                :on-price-input="onPriceInput"
                :on-line-discount-change="onLineDiscountChange"
                :update-line-total="updateLineTotal"
                :money="money"
                :money4="money4"
                @paste="pasteImportVisible = true"
                @copy="copyLine"
                @add-blank="addBlankLine"
                @remove="removeLine"
              />

              <InvoiceAccessoryTable
                class="form-card"
                :items="accessoryItems"
                :options="accessoryOptions"
                :loading="accessoryLoading"
                :search-options="searchAccessoryOptions"
                :money="money"
                :money4="money4"
                @add="addAccessory"
                @select="selectAccessory"
                @change="updateAccessoryTotal"
                @remove="removeAccessory"
              />

              <!-- 卡片 4：物流与备注（快递渠道必填单选 → 指定跟单员 → 备注） -->
              <section class="form-card">
                <div class="card-title"><span class="step">4</span>物流与备注</div>
                <el-form-item label="快递渠道" required>
                  <el-radio-group v-model="form.express_channel" class="express-radio-row">
                    <el-radio v-for="option in EXPRESS_CHANNEL_OPTIONS" :key="option" :value="option">{{ option }}</el-radio>
                  </el-radio-group>
                </el-form-item>
                <el-form-item label="指定跟单员">
                  <el-select
                    v-model="form.merchandiser_id"
                    clearable
                    filterable
                    placeholder="选择具有「跟单员」角色的用户"
                    style="width: 320px"
                  >
                    <el-option
                      v-for="user in merchandiserOptions"
                      :key="user.id"
                      :label="`${user.real_name}（${user.username}）`"
                      :value="user.id"
                    />
                  </el-select>
                </el-form-item>
                <el-form-item label="备注" class="remark-gold-item">
                  <el-input
                    v-model="form.remark"
                    type="textarea"
                    class="remark-gold"
                    :autosize="{ minRows: 2, maxRows: 4 }"
                    maxlength="500"
                  />
                  <div class="field-tip">备注内容将自动带入到出库单中</div>
                </el-form-item>
              </section>
            </main>

            <!-- 右窗格：金额/结算/回款，独立滚动 -->
            <aside class="pane pane-side">
              <InvoiceSummaryCard
                class="form-card"
                :form="form"
                :total="formTotal"
                :base-amount="formBaseAmount"
                :hair-amount="formHairPrice"
                :hair-discount="formLineDiscountTotal"
                :accessory-amount="formAccessoryAmount"
                :accessory-discount="formAccessoryDiscount"
                :money="money"
              />

              <InvoiceSettlementFields
                class="form-card"
                :form="form"
                :total="formTotal"
                :settlement-error="settlementError"
                :payment-methods="PAYMENT_METHOD_OPTIONS"
                :total-discount="formHairDiscountAbs"
                :money="money"
                :on-payment-method-change="onPaymentMethodChange"
                :on-handling-fee-input="markHandlingFeeTouched"
                :on-total-discount-change="applyTotalDiscount"
              />

              <InvoiceReceiptFields class="form-card" :form="form" />
            </aside>
          </div>
        </el-form>
      </template>

      <template #footer>
        <InvoiceTotalsFooter
          :form="form"
          :total="formTotal"
          :base-amount="formBaseAmount"
          :money="money"
          :syncing="saveAndSyncSubmitting"
          :sync-blocked="linkedTaskActive"
          sync-blocked-reason="请先在上方处理未结束的关联同步任务"
          @cancel="drawerVisible = false"
          @save="saveDraft"
          @sync="saveAndSync"
        />
      </template>
    </el-drawer>

    <InvoicePasteImport
      v-model="pasteImportVisible"
      :customer-id="form.customer_id"
      :customer-name="form.customer_name"
      :order-type="form.order_type"
      :currency="form.currency"
      :existing-items="form.items"
      @append="appendPastedLines"
    />

    <ShipmentSettlementDialog v-if="shipmentInvoice" :invoice="shipmentInvoice" @close="shipmentInvoice = null" @saved="refreshUpdate" />
    <InvoiceScreenshotImport
      :presale-enabled="shipmentCapabilities.enabled"
      v-model="screenshotImportVisible"
      @apply="applyScreenshotPreview"
    />

    <InvoiceWholeOrderPaste
      v-model="wholeOrderPasteVisible"
      :match-customer="matchWholeOrderCustomer"
      :customer-id="form.customer_id"
      :order-type="form.order_type"
      :currency="form.currency"
      @apply="applyWholeOrderPaste"
    />

    <!-- 旧版下单抽屉（过渡期）：与新版共享编辑器状态和整单粘贴对话框，
         产品明细的「从 Excel 粘贴」入口也在两版中共用。 -->
    <InvoiceLegacyDrawer
      :editor="editor"
      :money="money"
      :money4="money4"
      @open-paste="wholeOrderPasteVisible = true"
      @open-legacy-paste="pasteImportVisible = true"
    />

    <InvoiceLifecycle v-if="lifecycleInvoiceId !== null" :key="lifecycleInvoiceId" ref="lifecycleRef" :invoice-id="lifecycleInvoiceId" @changed="refreshUpdate" />

    <InvoiceSyncLogsDialog
      v-model="syncLogsVisible"
      :title="syncLogsTitle"
      :loading="syncLogsLoading"
      :rows="syncLogs"
      :format-date-time="formatDateTime"
      :action-text="actionText"
    />
  </div>
</template>

<script setup>
import ShipmentSettlementDialog from './components/ShipmentSettlementDialog.vue'
import { useInvoiceShipments, orderTypeLabel } from './composables/useInvoiceShipments'
import { useInvoiceImportDialogs } from './composables/useInvoiceImportDialogs'
import InvoiceLifecycle from './components/InvoiceLifecycle.vue'
import { computed, nextTick, ref } from 'vue'
import { ArrowDown, Box, Calendar, Delete, Document, Download, Edit, Refresh, RefreshLeft, Search, Tools } from '@element-plus/icons-vue'
import { EXPRESS_CHANNEL_OPTIONS, PAYMENT_METHOD_OPTIONS } from './composables/invoiceSettlement'
import { useInvoiceEditor } from './composables/useInvoiceEditor'
import { useInvoiceManagePage } from './composables/useInvoiceManagePage'
import InvoicePasteImport from './components/InvoicePasteImport.vue'
import InvoiceWholeOrderPaste from './components/InvoiceWholeOrderPaste.vue'
import InvoiceLegacyDrawer from './components/legacy/InvoiceLegacyDrawer.vue'
import InvoiceOrderCustomerFields from './components/InvoiceOrderCustomerFields.vue'
import InvoiceScreenshotImport from './components/InvoiceScreenshotImport.vue'
import InvoiceSyncLogsDialog from './components/InvoiceSyncLogsDialog.vue'
import InvoiceAccessoryTable from './components/InvoiceAccessoryTable.vue'
import InvoiceReceiptFields from './components/InvoiceReceiptFields.vue'
import InvoiceSettlementFields from './components/InvoiceSettlementFields.vue'
import InvoiceSummaryCard from './components/InvoiceSummaryCard.vue'
import InvoiceTotalsFooter from './components/InvoiceTotalsFooter.vue'
import InvoiceOverview from './components/InvoiceOverview.vue'
import LinkedSyncResult from './components/LinkedSyncResult.vue'
import InvoiceHairTable from './components/InvoiceHairTable.vue'
import TableTools from '@/components/TableTools.vue'
import FilterBar from '@/components/FilterBar.vue'
import ListPageStatus from '@/components/ListPageStatus.vue'

const { shipmentInvoice, shipmentCapabilities } = useInvoiceShipments()
const listPage = useInvoiceManagePage()
const {
  handleTableSort, actionText, bindIssueHandler, filters, formatDateTime, handleExport, invoices, loadInvoices,
  loading, money, money4, openSyncLogs, page, pageSize, total, removeInvoice, statusText, statusType,
  listErrorMessage, hasLoaded, hasData, dataPage, hasPendingSearch, handleSearch, handlePageChange, handleSaved, refreshUpdate,
  summary, summaryDateRange, summaryError, summaryLoading, loadSummary,
  syncLogs, syncLogsLoading, syncLogsTitle, syncLogsVisible, syncText, syncType,
  isInvoiceSyncing, resolveUncertain, validateAndSync,
  hasActiveFilters, handleSizeChange, orderTypeTone, resetFilters, statusOptions,
  columnDefs, density, densityClass, isFullscreen, panelRef, toggleFullscreen, visibleColumns, visibleKeys,
} = listPage
const editor = useInvoiceEditor({ onSaved: handleSaved })
const {
  drawerVisible, legacyVisible, customerLoading, customerOptions, salesUserOptions, selectedCustomer, customerRule,
  customerTotal, customerHasMore, loadMoreCustomers, privateOnlyCompany,
  canTogglePrivate, okkiBound, invoiceNoTaken, entryOptions, form, hairItems, accessoryItems,
  saveAndSyncSubmitting,
  linkedOperation, linkedBusy, linkedLoading, refreshLinked, retryLinked, recheckLinked, closeLinked, resolveLinked,
  accessoryOptions, accessoryLoading, formHairPrice, formLineDiscountTotal, formAccessoryAmount,
  formAccessoryDiscount, formBaseAmount, formTotal, lastOrderDate, settlementError, isProduction,
  searchCustomers, selectSyncedCustomer,
  onCustomerChange, onSalesUserChange, onCurrencyChange,  onInvoiceNoInput, onInvoiceNoBlur, openCreate, openEdit,
  applyScreenshotPreview,
  addBlankLine, copyLine, addAccessory, selectAccessory, removeAccessory, searchAccessoryOptions,
  updateAccessoryTotal, removeLine, loadLineOptions, onLineFilterChange, onCustomFieldChange,
  onPriceInput, onLineDiscountChange, updateLineTotal, appendImportedLines, saveDraft,
  saveAndSync, showIssues, markCustomerGradeTouched, markOkkiFlagTouched, onPaymentMethodChange, markHandlingFeeTouched,
  merchandiserOptions, previousInvoiceNo, formHairDiscountAbs, applyTotalDiscount,
  matchWholeOrderCustomer, applyWholeOrderPaste, openLegacyCreate,
} = editor
const linkedTaskActive = computed(() => linkedLoading.value || linkedBusy.value ||
  ['pending', 'running', 'failed', 'uncertain'].includes(linkedOperation.value?.status))
bindIssueHandler(showIssues)
const { pasteImportVisible, screenshotImportVisible, canPasteImport, pasteImportDisabledReason,
  appendPastedLines } = useInvoiceImportDialogs(form, appendImportedLines)
const wholeOrderPasteVisible = ref(false)
const lifecycleInvoiceId = ref(null)
const lifecycleRef = ref(null)
async function openLifecycle(row) {
  const invoiceId = row.id
  lifecycleInvoiceId.value = invoiceId
  await nextTick()
  if (lifecycleInvoiceId.value === invoiceId) lifecycleRef.value?.open()
}
const drawerTitle = computed(() => {
  const typeLabel = orderTypeLabel(form.order_type)
  return form.id ? `编辑${typeLabel} ${form.invoice_no}` : `新建${typeLabel}`
})
</script>

<style scoped src="./invoice-manage.css"></style>
