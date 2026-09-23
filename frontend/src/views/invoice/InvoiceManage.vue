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
      <div class="header-actions">
        <GlassButton v-permission="'invoice:write'" variant="secondary" :left-icon="Picture" @click="screenshotImportVisible = true">
          AI 识别 OKKI 截图
        </GlassButton>
        <GlassButton v-permission="'invoice:write'" variant="primary" :left-icon="Plus" class="primary-action" @click="openCreate('stock')">
          新建库存单
        </GlassButton>
        <GlassButton v-permission="'invoice:write'" variant="secondary" :left-icon="Plus" @click="openCreate('production')">
          新建生产单
        </GlassButton>
        <GlassButton v-permission="'invoice:write'" :disabled="!shipmentCapabilities.enabled" @click="openCreate('presale')">新建预售单</GlassButton>
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
      </div>
    </div>

    <el-alert v-if="!shipmentCapabilities.enabled" :title="shipmentCapabilities.reason || '预售出库暂未启用'" type="info" :closable="false" />
    <div class="summary-grid">
      <div class="summary-card lg-card">
        <span>发票数</span>
        <strong>{{ summary.total }}</strong>
      </div>
      <div class="summary-card lg-card">
        <span>可同步</span>
        <strong>{{ summary.ready }}</strong>
      </div>
      <div class="summary-card lg-card">
        <span>草稿</span>
        <strong>{{ summary.draft }}</strong>
      </div>
      <div class="summary-card emphasis lg-card">
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
          <el-option label="预售单" value="presale" />
        </el-select>
        <el-select v-model="filters.status" clearable placeholder="状态" style="width: 150px">
          <el-option label="草稿" value="draft" />
          <el-option label="取消处理中" value="cancel_pending" />
          <el-option label="已取消" value="cancelled" />
          <el-option label="可同步" value="ready" />
          <el-option label="已同步" value="synced" />
          <el-option label="同步失败" value="sync_failed" />
          <el-option label="同步结果待核对" value="sync_uncertain" />
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
              {{ orderTypeLabel(row.order_type) }}
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
        <el-table-column class-name="table-action-column" label="操作" min-width="356" max-width="390" fixed="right">
          <template #default="{ row }">
            <div class="table-actions">
              <el-button v-permission="'invoice:write'" link type="primary" :disabled="['cancel_pending','cancelled'].includes(row.status)" @click="openEdit(row.id)">
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
              <el-button v-permission="'invoice:read'" link @click="openSyncLogs(row)">
                <el-icon><Document /></el-icon>
                日志
              </el-button>
              <el-dropdown
                v-if="row.sync_status === 'sync_uncertain'"
                v-permission="'invoice:admin'"
                trigger="click"
                @command="command => resolveUncertain(row, command)"
              >
                <el-button link type="danger">处理待核对</el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item v-if="!row.xiaoman_order_id" command="bind_order">绑定已生成订单</el-dropdown-item>
                    <el-dropdown-item v-if="!row.xiaoman_order_id" command="confirm_not_created">确认未生成并允许重试</el-dropdown-item>
                    <el-dropdown-item v-if="row.xiaoman_order_id" command="confirm_existing">核实原订单更新结果</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
              <el-button v-if="row.order_type === 'presale'" v-permission="'shipment:write'" link type="primary" :disabled="!shipmentCapabilities.enabled || row.sync_status !== 'synced' || ['cancel_pending','cancelled'].includes(row.status)" @click="shipmentInvoice = row">生成出库单</el-button>
              <InvoiceLifecycle :invoice-id="row.id" @changed="loadInvoices" />
              <el-button v-if="!row.xiaoman_order_id && !['cancel_pending','cancelled'].includes(row.status)" v-permission="'invoice:write'" link type="danger" @click="removeInvoice(row)">
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
        <el-form ref="formRef" :model="form" label-position="top" class="invoice-form">
          <div class="drawer-panes">
            <!-- 左窗格：录入主流（客户/订单 → 产品明细 → 配件明细），独立滚动 -->
            <main class="pane pane-main">
              <section class="form-card">
                <div class="card-title">
                  <span class="step">1</span>订单与客户
                  <el-button class="card-title-action" size="small" v-permission="'invoice:write'" @click="wholeOrderPasteVisible = true">
                    <el-icon><DocumentCopy /></el-icon>整单粘贴
                  </el-button>
                </div>
                <div class="fgrid">
                  <el-form-item label="订单归属业务员" required>
                    <el-select
                      v-model="form.sales_user_id"
                      filterable
                      :disabled="Boolean(form.id)"
                      placeholder="选择客户及业绩归属业务员"
                      style="width: 100%"
                      @change="onSalesUserChange"
                    >
                      <el-option
                        v-for="user in salesUserOptions"
                        :key="user.id"
                        :label="`${user.real_name}（${user.username}）${user.okki_bound ? '' : ' · 未绑定OKKI'}${user.okki_department_configured ? '' : ' · 未配置部门'}`"
                        :value="user.id"
                      />
                    </el-select>
                  </el-form-item>
                  <el-form-item label="客户" required>
                    <div class="customer-filter-row">
                      <el-select
                        v-model="selectedCustomer"
                        value-key="option_key"
                        filterable
                        remote
                        reserve-keyword
                        :remote-method="searchCustomers"
                        :loading="customerLoading"
                        placeholder="输入客户名称、ID 或联系人姓名"
                        class="customer-filter-select"
                        @change="onCustomerChange"
                      >
                        <el-option
                          v-for="customer in customerOptions"
                          :key="customer.option_key"
                          :label="customerOptionLabel(customer)"
                          :value="customer"
                        />
                        <template #footer>
                          <span>共 {{ customerTotal }} 项匹配</span>
                          <el-button v-if="customerHasMore" link type="primary" :loading="customerLoading" @click="loadMoreCustomers">
                            加载更多
                          </el-button>
                        </template>
                      </el-select>
                      <el-checkbox v-permission="'invoice_private_filter:read'" v-model="privateOnlyCompany" class="customer-filter-check">仅私海</el-checkbox>
                    </div>
                    <div v-if="!okkiBound && privateOnlyCompany" class="binding-helper">
                      {{ canTogglePrivate
                        ? '未绑定 OKKI，私海筛选无结果。请取消“仅私海”或前往外部账号绑定。'
                        : '未绑定 OKKI，暂无法搜索私海客户。请到 系统管理 → 外部账号绑定 处理。' }}
                    </div>
                    <InvoiceCustomerSyncEntry :on-select="selectSyncedCustomer" />
                    <div v-if="customerRule" class="rule-badge">该客户价格规则：{{ describeCustomerRule(customerRule) }}</div>
                  </el-form-item>
                  <el-form-item label="客户等级" required>
                    <el-select v-model="form.customer_grade" @change="markCustomerGradeTouched" placeholder="请选择等级" :disabled="!form.customer_id">
                      <el-option v-for="grade in ['S', 'A', 'B', 'C', 'D']" :key="grade" :label="grade" :value="grade" />
                    </el-select>
                  </el-form-item>
                  <!-- 业务员信息只读资料条：替代原来 3 个独占一整段的只读输入框 -->
                  <div class="fgrid-c3 sales-readout">
                    <span>From <b>{{ form.sales_user_name || '—' }}</b></span>
                    <span class="sep">|</span>
                    <span>{{ form.sales_phone || '—' }}</span>
                    <span class="sep">|</span>
                    <span>{{ form.sales_email || '—' }}</span>
                    <template v-if="lastOrderDate">
                      <span class="sep">|</span>
                      <span>上次订单成交日期 <b>{{ lastOrderDate }}</b></span>
                    </template>
                  </div>
                  <el-form-item label="联系人" required>
                    <el-input v-model="form.contact_name" maxlength="100" placeholder="To" />
                  </el-form-item>
                  <el-form-item label="电话" required>
                    <el-input v-model="form.contact_phone" maxlength="50" placeholder="TEL/Fax" />
                  </el-form-item>
                  <el-form-item label="邮箱" required>
                    <el-input v-model="form.contact_email" maxlength="100" placeholder="E-mail" />
                  </el-form-item>
                  <el-form-item label="收货地址" required class="fgrid-c3">
                    <el-input v-model="form.delivery_address" type="textarea" :autosize="{ minRows: 1, maxRows: 3 }" maxlength="500" placeholder="Delivery address" />
                  </el-form-item>
                </div>

                <div class="subdiv">订单信息</div>

                <div class="fgrid">
                  <el-alert
                    v-if="form.source_type === 'okki_screenshot'"
                    class="fgrid-c3 source-order-alert"
                    title="来自外部 OKKI 截图；保存并同步时会校验本系统 OKKI 是否已有同一订单。"
                    type="info"
                    :closable="false"
                    show-icon
                  />
                  <el-form-item label="订单号/发票号" :error="invoiceNoTaken ? '该单号已存在，请更换' : ''">
                    <el-input
                      v-model="form.invoice_no"
                      maxlength="64"
                      placeholder="已自动生成，可修改"
                      @input="onInvoiceNoInput"
                      @blur="onInvoiceNoBlur"
                    />
                    <div v-if="previousInvoiceNo" class="prev-order-tip">该业务员上一张{{ form.order_type === 'production' ? '生产单' : '库存单' }}：{{ previousInvoiceNo }}</div>
                  </el-form-item>
                  <el-form-item label="下单日期" required>
                    <el-date-picker v-model="form.invoice_date" value-format="YYYY-MM-DD" style="width: 100%" />
                  </el-form-item>
                  <el-form-item label="币种">
                    <el-input v-model="form.currency" maxlength="16" @change="onCurrencyChange" />
                  </el-form-item>
                  <el-form-item label="小满标记" required class="fgrid-c3">
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
                      <span class="okki-flag-tip">推小满必填，已按历史预判</span>
                    </div>
                  </el-form-item>
                </div>
              </section>

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

    <ShipmentSettlementDialog v-if="shipmentInvoice" :invoice="shipmentInvoice" @close="shipmentInvoice = null" @saved="loadInvoices" />
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

    <!-- 旧版下单抽屉（过渡期）：与新版共享编辑器状态；整单粘贴对话框两版共用 -->
    <InvoiceLegacyDrawer :editor="editor" :money="money" :money4="money4" @open-paste="wholeOrderPasteVisible = true" />

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
import { computed, ref } from 'vue'
import { ArrowDown, Delete, Document, DocumentCopy, Download, Edit, Picture, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { EXPRESS_CHANNEL_OPTIONS, PAYMENT_METHOD_OPTIONS } from './composables/invoiceSettlement'
import { customerOptionLabel } from './composables/useInvoiceCustomerSearch'
import { describeCustomerRule, useInvoiceEditor } from './composables/useInvoiceEditor'
import { useInvoiceManagePage } from './composables/useInvoiceManagePage'
import InvoicePasteImport from './components/InvoicePasteImport.vue'
import InvoiceWholeOrderPaste from './components/InvoiceWholeOrderPaste.vue'
import InvoiceLegacyDrawer from './components/legacy/InvoiceLegacyDrawer.vue'
import InvoiceCustomerSyncEntry from './components/InvoiceCustomerSyncEntry.vue'
import InvoiceScreenshotImport from './components/InvoiceScreenshotImport.vue'
import InvoiceSyncLogsDialog from './components/InvoiceSyncLogsDialog.vue'
import InvoiceAccessoryTable from './components/InvoiceAccessoryTable.vue'
import InvoiceReceiptFields from './components/InvoiceReceiptFields.vue'
import InvoiceSettlementFields from './components/InvoiceSettlementFields.vue'
import InvoiceSummaryCard from './components/InvoiceSummaryCard.vue'
import InvoiceTotalsFooter from './components/InvoiceTotalsFooter.vue'
import InvoiceHairTable from './components/InvoiceHairTable.vue'

const { shipmentInvoice, shipmentCapabilities } = useInvoiceShipments()
const page = useInvoiceManagePage()
const {
  actionText, bindIssueHandler, filters, formatDateTime, handleExport, invoices, loadInvoices,
  loading, money, money4, openSyncLogs, pagination, removeInvoice, statusText, statusType,
  summary, syncLogs, syncLogsLoading, syncLogsTitle, syncLogsVisible, syncText, syncType,
  isInvoiceSyncing, resolveUncertain, validateAndSync,
} = page
const editor = useInvoiceEditor({ onSaved: loadInvoices })
const {
  drawerVisible, legacyVisible, customerLoading, customerOptions, salesUserOptions, selectedCustomer, customerRule,
  customerTotal, customerHasMore, loadMoreCustomers, privateOnlyCompany,
  canTogglePrivate, okkiBound, invoiceNoTaken, entryOptions, form, hairItems, accessoryItems,
  saveAndSyncSubmitting,
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
bindIssueHandler(showIssues)
const { pasteImportVisible, screenshotImportVisible, canPasteImport, pasteImportDisabledReason,
  appendPastedLines } = useInvoiceImportDialogs(form, appendImportedLines)
const wholeOrderPasteVisible = ref(false)
const drawerTitle = computed(() => {
  const typeLabel = orderTypeLabel(form.order_type)
  return form.id ? `编辑${typeLabel} ${form.invoice_no}` : `新建${typeLabel}`
})
</script>

<style scoped src="./invoice-manage.css"></style>
