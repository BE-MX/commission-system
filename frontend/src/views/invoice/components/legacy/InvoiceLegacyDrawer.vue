<template>
  <!-- 旧版下单抽屉（过渡期）：HEAD 版布局原样保留，与新版共享同一编辑器状态。
       新业务请走新版下单页；旧版只提供库存单/生产单新建入口，编辑仍走新版。 -->
  <el-drawer v-model="legacyVisible" :title="drawerTitle" size="94%" class="legacy-editor-drawer">
    <template #default>
      <div class="legacy-toolbar">
        <el-button size="small" v-permission="'invoice:write'" @click="$emit('open-paste')">
          <el-icon><DocumentCopy /></el-icon>整单粘贴
        </el-button>
        <span class="legacy-note">旧版布局 · 过渡期内提供；快递渠道、联系人、客户等级为必填（与新版同口径）</span>
      </div>
      <el-form :model="form" label-width="80px" class="invoice-form">
        <section class="head-section">
          <div class="col-title">客户信息</div>
          <div class="head-grid">
            <el-form-item label="订单归属业务员" required class="span-3">
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
            <el-form-item label="客户" required class="span-3">
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
            <el-form-item label="联系人" required class="span-2">
              <el-input v-model="form.contact_name" maxlength="100" placeholder="To" />
            </el-form-item>
            <el-form-item label="电话" required class="span-2">
              <el-input v-model="form.contact_phone" maxlength="50" placeholder="TEL/Fax" />
            </el-form-item>
            <el-form-item label="邮箱" required class="span-2">
              <el-input v-model="form.contact_email" maxlength="100" placeholder="E-mail" />
            </el-form-item>
            <el-form-item label="收货地址" required class="span-6">
              <el-input v-model="form.delivery_address" type="textarea" :autosize="{ minRows: 1, maxRows: 3 }" maxlength="500" placeholder="Delivery address" />
            </el-form-item>
          </div>
        </section>

        <section class="head-section">
          <div class="col-title">业务员信息</div>
          <div class="head-grid">
            <el-form-item label="业务员" class="span-2">
              <el-input v-model="form.sales_user_name" maxlength="50" placeholder="From" readonly />
            </el-form-item>
            <el-form-item label="业务电话" class="span-2">
              <el-input v-model="form.sales_phone" maxlength="50" readonly />
            </el-form-item>
            <el-form-item label="业务邮箱" class="span-2">
              <el-input v-model="form.sales_email" maxlength="100" readonly />
            </el-form-item>
          </div>
        </section>

        <section class="head-section">
          <div class="col-title">订单信息</div>
          <div class="head-grid">
            <el-alert
              v-if="form.source_type === 'okki_screenshot'"
              class="span-6 source-order-alert"
              title="来自外部 OKKI 截图；保存并同步时会校验本系统 OKKI 是否已有同一订单。"
              type="info"
              :closable="false"
              show-icon
            />
            <el-form-item label="订单号/发票号" class="span-2" :error="invoiceNoTaken ? '该单号已存在，请更换' : ''">
              <el-input
                v-model="form.invoice_no"
                maxlength="64"
                placeholder="已自动生成，可修改"
                @input="onInvoiceNoInput"
                @blur="onInvoiceNoBlur"
              />
            </el-form-item>
            <el-form-item label="下单日期" required class="span-2">
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
              <div class="field-tip">备注内容将自动带入到出库单中</div>
            </el-form-item>
          </div>
        </section>

        <InvoiceLegacySettlementFields
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

        <InvoiceLegacyReceiptFields :form="form" :total="formTotal" />

        <InvoiceHairTable
          :items="hairItems"
          :is-production="isProduction"
          :entry-options="entryOptions"
          :load-line-options="loadLineOptions"
          :on-line-filter-change="onLineFilterChange"
          :on-custom-field-change="onCustomFieldChange"
          :on-price-input="onPriceInput"
          :on-line-discount-change="onLineDiscountChange"
          :update-line-total="updateLineTotal"
          :money="money"
          :money4="money4"
          @copy="copyLine"
          @add-blank="addBlankLine"
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
      <InvoiceLegacyTotalsFooter
        :form="form"
        :total="formTotal"
        :base-amount="formBaseAmount"
        :hair-amount="formHairPrice"
        :hair-discount="formLineDiscountTotal"
        :accessory-amount="formAccessoryAmount"
        :accessory-discount="formAccessoryDiscount"
        :money="money"
        :syncing="saveAndSyncSubmitting"
        @cancel="legacyVisible = false"
        @save="saveDraft"
        @sync="saveAndSync"
      />
    </template>
  </el-drawer>
</template>

<script setup>
import { computed } from 'vue'
import { DocumentCopy } from '@element-plus/icons-vue'
import { EXPRESS_CHANNEL_OPTIONS, PAYMENT_METHOD_OPTIONS } from '../../composables/invoiceSettlement'
import { customerOptionLabel } from '../../composables/useInvoiceCustomerSearch'
import { describeCustomerRule } from '../../composables/useInvoiceEditor'
import InvoiceCustomerSyncEntry from '../InvoiceCustomerSyncEntry.vue'
import InvoiceHairTable from '../InvoiceHairTable.vue'
import InvoiceAccessoryTable from '../InvoiceAccessoryTable.vue'
import InvoiceLegacySettlementFields from './InvoiceLegacySettlementFields.vue'
import InvoiceLegacyReceiptFields from './InvoiceLegacyReceiptFields.vue'
import InvoiceLegacyTotalsFooter from './InvoiceLegacyTotalsFooter.vue'

const props = defineProps({
  editor: { type: Object, required: true }, // useInvoiceEditor 整包：与新版共享同一份状态
  money: { type: Function, required: true },
  money4: { type: Function, required: true },
})
defineEmits(['open-paste'])

const {
  legacyVisible, form, selectedCustomer, customerOptions, customerLoading, salesUserOptions,
  customerRule, customerTotal, customerHasMore, loadMoreCustomers, privateOnlyCompany, canTogglePrivate,
  okkiBound, invoiceNoTaken, entryOptions, hairItems, accessoryItems, accessoryOptions, accessoryLoading,
  formHairPrice, formLineDiscountTotal, formAccessoryAmount, formAccessoryDiscount, formBaseAmount, formTotal,
  lastOrderDate, settlementError, isProduction, saveAndSyncSubmitting,
  searchCustomers, selectSyncedCustomer, onCustomerChange, onSalesUserChange, onCurrencyChange,
  onInvoiceNoInput, onInvoiceNoBlur, addBlankLine, copyLine, addAccessory, selectAccessory,
  removeAccessory, searchAccessoryOptions, updateAccessoryTotal, removeLine, loadLineOptions,
  onLineFilterChange, onCustomFieldChange, onPriceInput, onLineDiscountChange, updateLineTotal,
  saveDraft, saveAndSync, markCustomerGradeTouched, markOkkiFlagTouched, onPaymentMethodChange, markHandlingFeeTouched,
} = props.editor

const drawerTitle = computed(() => {
  const typeLabel = form.order_type === 'production' ? '生产单' : '库存单'
  return form.id ? `编辑${typeLabel} ${form.invoice_no}（旧版）` : `新建${typeLabel}（旧版）`
})
</script>

<style scoped>
/* HEAD 版抽屉布局样式（invoice-manage.css 2026-09 改版前），仅作用于旧版抽屉 */
.legacy-toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.legacy-note { font-size: 12px; color: var(--text-muted); }

.invoice-form { --el-component-size: 36px; padding-right: 12px; }
.invoice-form :deep(.el-input__wrapper),
.invoice-form :deep(.el-select__wrapper) { min-height: 36px; box-sizing: border-box; }
.invoice-form :deep(.el-input__inner) { height: auto; }
.invoice-form :deep(.el-textarea__inner) { min-height: 36px !important; box-sizing: border-box; padding-top: 7px; padding-bottom: 7px; }
.invoice-form :deep(.el-form-item__label) { color: var(--text-secondary); font-weight: 600; }
.invoice-form :deep(.el-form-item) { margin-bottom: 10px; }

.source-order-alert { margin-bottom: 14px; }

.col-title { margin: 2px 0 10px; font-size: 14px; font-weight: 700; color: var(--text-secondary); letter-spacing: 0.02em; }
.head-section { max-width: 1400px; padding-bottom: 2px; margin-bottom: 10px; border-bottom: 1px solid var(--border-color); }
.head-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 0 16px; align-items: start; }
.head-grid .span-1 { grid-column: span 1; }
.head-grid .span-2 { grid-column: span 2; }
.head-grid .span-3 { grid-column: span 3; }
.head-grid .span-6 { grid-column: 1 / -1; }
.head-grid :deep(.el-form-item__content) { width: 100%; min-width: 0; }
.head-grid .span-1 :deep(.el-form-item__content) { max-width: 180px; }
.head-grid .span-2 :deep(.el-form-item__content) { max-width: 360px; }
.head-grid .span-3 :deep(.el-form-item__content) { max-width: 560px; }
.head-grid .span-6 :deep(.el-form-item__content) { max-width: 720px; }

.field-tip { margin-top: 4px; font-size: 11.5px; line-height: 1.4; color: var(--text-muted); }

.rule-badge { margin-top: 4px; padding: 2px 10px; border-radius: 999px; background: var(--color-primary-light); color: var(--color-primary); font-size: 12px; font-weight: 600; width: fit-content; }
.binding-helper { margin-top: 6px; color: var(--color-warning-text); font-size: 12px; line-height: 1.5; }

.customer-filter-row { display: flex; align-items: center; gap: 8px; width: 100%; }
.customer-filter-select { flex: 1; min-width: 0; }
.customer-filter-check { flex-shrink: 0; }

.okki-flags-row { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 14px; width: 100%; }
.okki-flag { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text-primary); }
.okki-flag-tip { font-size: 12px; color: var(--text-secondary); }
.okki-last-order { font-size: 12px; color: var(--text-secondary); font-variant-numeric: tabular-nums; }

.legacy-editor-drawer :deep(.el-drawer__body) { padding-top: 18px; }
.legacy-editor-drawer :deep(.el-drawer__footer) { border-top: 1px solid var(--border-color); background: rgba(250, 251, 254, 0.96); }

@media (max-width: 1100px) {
  .head-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .head-grid .span-1, .head-grid .span-2 { grid-column: span 1; }
  .head-grid .span-3, .head-grid .span-6 { grid-column: 1 / -1; }
}
@media (max-width: 900px) {
  .head-grid { grid-template-columns: 1fr; }
  .head-grid .span-1, .head-grid .span-2, .head-grid .span-3, .head-grid .span-6 { grid-column: 1 / -1; }
}
@media (max-width: 560px) {
  .head-grid .span-1 :deep(.el-form-item__content),
  .head-grid .span-2 :deep(.el-form-item__content),
  .head-grid .span-3 :deep(.el-form-item__content),
  .head-grid .span-6 :deep(.el-form-item__content) { max-width: none; }
}
</style>
