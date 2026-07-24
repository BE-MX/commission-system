<template>
  <div class="invoice-page">
    <div class="page-header">
      <div>
        <h2>订单发票管理</h2>
        <p>客户发票、产品明细、价格管控、导出与小满同步集中处理。</p>
      </div>
      <div class="header-actions">
        <el-button v-permission="'invoice:write'" type="primary" class="primary-action" @click="openCreate('stock')">
          <el-icon><Plus /></el-icon>
          新建库存单
        </el-button>
        <el-button v-permission="'invoice:write'" @click="openCreate('production')">
          <el-icon><Plus /></el-icon>
          新建生产单
        </el-button>
      </div>
    </div>

    <div class="summary-grid">
      <div class="summary-card">
        <span>发票数</span>
        <strong>{{ summary.total }}</strong>
      </div>
      <div class="summary-card">
        <span>可同步</span>
        <strong>{{ summary.ready }}</strong>
      </div>
      <div class="summary-card">
        <span>草稿</span>
        <strong>{{ summary.draft }}</strong>
      </div>
      <div class="summary-card emphasis">
        <span>当前页金额</span>
        <strong>USD {{ money(summary.amount) }}</strong>
      </div>
    </div>

    <section class="table-card invoice-panel">
      <div class="toolbar">
        <el-input
          v-model="filters.keyword"
          clearable
          placeholder="搜索发票号/客户"
          style="width: 260px"
          @keyup.enter="loadInvoices"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-select v-model="filters.order_type" clearable placeholder="订单类型" style="width: 130px">
          <el-option label="库存单" value="stock" />
          <el-option label="生产单" value="production" />
        </el-select>
        <el-select v-model="filters.status" clearable placeholder="状态" style="width: 150px">
          <el-option label="草稿" value="draft" />
          <el-option label="可同步" value="ready" />
          <el-option label="已同步" value="synced" />
          <el-option label="同步失败" value="sync_failed" />
        </el-select>
        <el-button @click="loadInvoices">
          <el-icon><Search /></el-icon>
          筛选
        </el-button>
      </div>

      <el-table v-loading="loading" :data="invoices" border class="list-table invoice-table">
        <template #empty>
          <div class="empty-state">
            <strong>暂无发票</strong>
            <span>新建一张发票后会显示在这里。</span>
          </div>
        </template>
        <el-table-column prop="invoice_no" label="发票号" min-width="132" max-width="170" show-overflow-tooltip />
        <el-table-column label="类型" min-width="76" max-width="96">
          <template #default="{ row }">
            <el-tag :type="row.order_type === 'production' ? 'warning' : 'info'" effect="plain">
              {{ row.order_type === 'production' ? '生产单' : '库存单' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="customer_name" label="客户" min-width="150" max-width="260" show-overflow-tooltip />
        <el-table-column prop="invoice_date" label="日期" min-width="96" max-width="120" show-overflow-tooltip />
        <el-table-column prop="item_count" label="明细" min-width="56" max-width="76" align="right" />
        <el-table-column label="金额" min-width="104" max-width="150" align="right">
          <template #default="{ row }">{{ row.currency }} {{ money(row.total_amount) }}</template>
        </el-table-column>
        <el-table-column label="状态" min-width="84" max-width="110">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" effect="plain">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="同步" min-width="84" max-width="110">
          <template #default="{ row }">
            <el-tag :type="syncType(row.sync_status)" effect="plain">{{ syncText(row.sync_status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建人" min-width="84" max-width="120" show-overflow-tooltip>
          <template #default="{ row }">{{ row.created_by_name || '-' }}</template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="130" max-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="356" max-width="390" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button v-permission="'invoice:write'" link type="primary" @click="openEdit(row.id)">
                <el-icon><Edit /></el-icon>
                编辑
              </el-button>
              <el-dropdown trigger="click" @command="cmd => handleExport(cmd, row)">
                <el-button link>
                  <el-icon><Download /></el-icon>
                  导出
                  <el-icon><ArrowDown /></el-icon>
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="excel">Excel</el-dropdown-item>
                    <el-dropdown-item command="pdf">PDF</el-dropdown-item>
                    <el-dropdown-item command="print">打印 / 预览</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
              <el-button v-permission="'invoice:sync'" link type="warning" @click="validateAndSync(row.id)">
                <el-icon><Refresh /></el-icon>
                同步
              </el-button>
              <el-button v-permission="'invoice:read'" link @click="openSyncLogs(row)">
                <el-icon><Document /></el-icon>
                日志
              </el-button>
              <el-button v-permission="'invoice:write'" link type="danger" @click="removeInvoice(row)">
                <el-icon><Delete /></el-icon>
                删除
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <div class="pagination-bar">
      <el-pagination
        v-model:current-page="pagination.page"
        v-model:page-size="pagination.page_size"
        :total="pagination.total"
        :page-sizes="[20, 50, 100]"
        layout="total,sizes,prev,pager,next,jumper"
        @size-change="loadInvoices"
        @current-change="loadInvoices"
      />
    </div>

    <el-drawer v-model="drawerVisible" :title="drawerTitle" size="94%">
      <template #default>
        <el-form ref="formRef" :model="form" label-width="80px" class="invoice-form">
          <section class="head-section">
            <div class="col-title">客户信息</div>
            <div class="head-grid">
              <el-form-item label="客户" required class="span-3">
                <div class="customer-filter-row">
                  <el-select
                    v-model="selectedCustomer"
                    value-key="company_id"
                    filterable
                    remote
                    reserve-keyword
                    :remote-method="searchCustomers"
                    :loading="customerLoading"
                    placeholder="输入客户名称/ID 搜索"
                    class="customer-filter-select"
                    @change="onCustomerChange"
                  >
                    <el-option
                      v-for="customer in customerOptions"
                      :key="customer.company_id"
                      :label="customerLabel(customer)"
                      :value="customer"
                    />
                  </el-select>
                  <el-checkbox v-permission="'invoice_private_filter:read'" v-model="privateOnlyCompany" class="customer-filter-check">仅私海</el-checkbox>
                </div>
                <div v-if="customerRule" class="rule-badge">
                  该客户价格规则：{{ describeCustomerRule(customerRule) }}
                </div>
              </el-form-item>
              <el-form-item label="按联系人" class="span-3">
                <div class="customer-filter-row">
                  <el-select
                    v-model="selectedContact"
                    value-key="contact_id"
                    filterable
                    remote
                    clearable
                    reserve-keyword
                    :remote-method="searchContacts"
                    :loading="contactLoading"
                    :placeholder="form.customer_id ? '搜索该客户的联系人' : '输入联系人姓名定位客户'"
                    class="customer-filter-select"
                    @change="onContactChange"
                  >
                    <el-option
                      v-for="contact in contactOptions"
                      :key="contact.contact_id"
                      :label="contactLabel(contact)"
                      :value="contact"
                    />
                  </el-select>
                  <el-checkbox v-permission="'invoice_private_filter:read'" v-model="privateOnlyContact" class="customer-filter-check">仅私海</el-checkbox>
                </div>
                <div v-if="!okkiBound && (privateOnlyCompany || privateOnlyContact)" class="binding-helper">
                  {{ canTogglePrivate
                    ? '未绑定 OKKI，私海筛选无结果。请取消“仅私海”或前往外部账号绑定。'
                    : '未绑定 OKKI，暂无法搜索私海客户。请到 系统管理 → 外部账号绑定 处理。' }}
                </div>
              </el-form-item>
              <el-form-item label="联系人" class="span-2">
                <el-input v-model="form.contact_name" maxlength="100" placeholder="To" />
              </el-form-item>
              <el-form-item label="电话" class="span-2">
                <el-input v-model="form.contact_phone" maxlength="50" placeholder="TEL/Fax" />
              </el-form-item>
              <el-form-item label="邮箱" class="span-2">
                <el-input v-model="form.contact_email" maxlength="100" placeholder="E-mail" />
              </el-form-item>
              <el-form-item label="收货地址" class="span-6">
                <el-input v-model="form.delivery_address" type="textarea" :autosize="{ minRows: 1, maxRows: 3 }" maxlength="500" placeholder="Delivery address" />
              </el-form-item>
            </div>
          </section>

          <section class="head-section">
            <div class="col-title">业务员信息</div>
            <div class="head-grid">
              <el-form-item label="业务员" class="span-2">
                <el-input v-model="form.sales_user_name" maxlength="50" placeholder="From" />
              </el-form-item>
              <el-form-item label="业务电话" class="span-2">
                <el-input v-model="form.sales_phone" maxlength="50" />
              </el-form-item>
              <el-form-item label="业务邮箱" class="span-2">
                <el-input v-model="form.sales_email" maxlength="100" />
              </el-form-item>
            </div>
          </section>

          <section class="head-section">
            <div class="col-title">订单信息</div>
            <div class="head-grid">
              <el-form-item label="发票号" class="span-2" :error="invoiceNoTaken ? '发票号已存在，请更换' : ''">
                <el-input
                  v-model="form.invoice_no"
                  maxlength="64"
                  placeholder="已自动生成，可修改"
                  @input="onInvoiceNoInput"
                  @blur="onInvoiceNoBlur"
                />
              </el-form-item>
              <el-form-item label="日期" required class="span-2">
                <el-date-picker v-model="form.invoice_date" value-format="YYYY-MM-DD" style="width: 100%" />
              </el-form-item>
              <el-form-item label="币种" class="span-1">
                <el-input v-model="form.currency" maxlength="16" @change="onCurrencyChange" />
              </el-form-item>
              <el-form-item label="小满标记" required class="span-3">
                <div class="okki-flags-row">
                  <span class="okki-flag">
                    新成交
                    <el-switch v-model="form.okki_new_deal" :active-value="1" :inactive-value="0"
                               @change="markOkkiFlagTouched('newDeal')" />
                  </span>
                  <span class="okki-flag">
                    包邮
                    <el-switch v-model="form.okki_free_shipping" :active-value="1" :inactive-value="0"
                               @change="markOkkiFlagTouched('freeShipping')" />
                  </span>
                  <span class="okki-flag">
                    首返
                    <el-switch v-model="form.okki_first_return" :active-value="1" :inactive-value="0" />
                  </span>
                  <span v-if="lastOrderDate" class="okki-last-order">上次订单成交日期：{{ lastOrderDate }}</span>
                  <span class="okki-flag-tip">推小满必填，已按历史预判</span>
                </div>
              </el-form-item>
              <el-form-item label="备注" class="span-3">
                <el-input v-model="form.remark" type="textarea" :autosize="{ minRows: 1, maxRows: 3 }" maxlength="500" />
              </el-form-item>
            </div>
          </section>

          <InvoiceSettlementFields
            :form="form"
            :total="formTotal"
            :settlement-error="settlementError"
            :hair-amount="formHairPrice"
            :hair-discount="formLineDiscountTotal"
            :accessory-amount="formAccessoryAmount"
            :accessory-discount="formAccessoryDiscount"
            :payment-methods="PAYMENT_METHOD_OPTIONS"
            :express-channels="EXPRESS_CHANNEL_OPTIONS"
            :money="money"
            :on-payment-method-change="onPaymentMethodChange"
            :on-handling-fee-input="markHandlingFeeTouched"
          />

          <InvoiceHairTable
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
            @add="addLine"
            @remove="removeLine"
          />

          <InvoiceAccessoryTable
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

        </el-form>
      </template>

      <template #footer>
        <InvoiceTotalsFooter
          :form="form"
          :total="formTotal"
          :base-amount="formBaseAmount"
          :hair-amount="formHairPrice"
          :hair-discount="formLineDiscountTotal"
          :accessory-amount="formAccessoryAmount"
          :accessory-discount="formAccessoryDiscount"
          :money="money"
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

    <el-dialog v-model="syncLogsVisible" :title="syncLogsTitle" width="720px">
      <el-table v-loading="syncLogsLoading" :data="syncLogs" border class="list-table" max-height="420">
        <el-table-column label="时间" min-width="150" max-width="170" show-overflow-tooltip>
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="动作" min-width="96" max-width="110">
          <template #default="{ row }">{{ actionText(row.action) }}</template>
        </el-table-column>
        <el-table-column label="结果" min-width="80" max-width="90">
          <template #default="{ row }">
            <el-tag :type="row.success ? 'success' : 'danger'" effect="plain">
              {{ row.success ? '成功' : '失败' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="信息" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">{{ row.error_message || (row.success ? 'OKKI 已受理' : '-') }}</template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowDown, Delete, Document, Download, Edit, Plus, Printer, Refresh, Search } from '@element-plus/icons-vue'
import { EXPRESS_CHANNEL_OPTIONS, PAYMENT_METHOD_OPTIONS } from './composables/invoiceSettlement'
import { contactLabel, customerLabel, describeCustomerRule, useInvoiceEditor } from './composables/useInvoiceEditor'
import { useInvoiceManagePage } from './composables/useInvoiceManagePage'
import InvoicePasteImport from './components/InvoicePasteImport.vue'
import InvoiceAccessoryTable from './components/InvoiceAccessoryTable.vue'
import InvoiceSettlementFields from './components/InvoiceSettlementFields.vue'
import InvoiceTotalsFooter from './components/InvoiceTotalsFooter.vue'
import InvoiceHairTable from './components/InvoiceHairTable.vue'

const page = useInvoiceManagePage()
const {
  actionText, bindIssueHandler, filters, formatDateTime, handleExport, invoices, loadInvoices,
  loading, money, money4, openSyncLogs, pagination, removeInvoice, statusText, statusType,
  summary, syncLogs, syncLogsLoading, syncLogsTitle, syncLogsVisible, syncText, syncType,
  validateAndSync,
} = page
const {
  drawerVisible, customerLoading, customerOptions, selectedCustomer, customerRule,
  contactLoading, contactOptions, selectedContact, privateOnlyCompany, privateOnlyContact,
  canTogglePrivate, okkiBound, invoiceNoTaken, entryOptions, form, hairItems, accessoryItems,
  accessoryOptions, accessoryLoading, formHairPrice, formLineDiscountTotal, formAccessoryAmount,
  formAccessoryDiscount, formBaseAmount, formTotal, lastOrderDate, settlementError, isProduction,
  searchCustomers, searchContacts,
  onCustomerChange, onCurrencyChange, onContactChange, onInvoiceNoInput, onInvoiceNoBlur, openCreate, openEdit,
  addLine, addAccessory, selectAccessory, removeAccessory, searchAccessoryOptions,
  updateAccessoryTotal, removeLine, loadLineOptions, onLineFilterChange, onCustomFieldChange,
  onPriceInput, onLineDiscountChange, updateLineTotal, appendImportedLines, saveDraft,
  saveAndSync, showIssues, markOkkiFlagTouched, onPaymentMethodChange, markHandlingFeeTouched,
} = useInvoiceEditor({ onSaved: loadInvoices })
bindIssueHandler(showIssues)

const pasteImportVisible = ref(false)
const canPasteImport = computed(() => Boolean(form.customer_id && form.order_type && form.currency))
const pasteImportDisabledReason = computed(() => {
  const missing = []
  if (!form.customer_id) missing.push('客户')
  if (!form.order_type) missing.push('订单类型')
  if (!form.currency) missing.push('币种')
  return missing.length ? `请先选择${missing.join('、')}` : ''
})
const drawerTitle = computed(() => {
  const typeLabel = form.order_type === 'production' ? '生产单' : '库存单'
  return form.id ? `编辑${typeLabel} ${form.invoice_no}` : `新建${typeLabel}`
})

function appendPastedLines({ rows, fingerprint }) {
  if (!appendImportedLines(rows, fingerprint)) {
    ElMessage.warning('这批数据已经加入当前发票')
    return
  }
  ElMessage.success(`已加入 ${rows.length} 条产品明细，发票尚未保存`)
}
</script>

<style scoped src="./invoice-manage.css"></style>
