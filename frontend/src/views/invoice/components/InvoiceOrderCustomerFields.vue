<template>
<section class="form-card invoice-order-fields">
  <div class="card-title">
    <span class="step">1</span>订单与客户
    <el-button class="card-title-action" v-permission="'invoice:write'" @click="$emit('open-whole-order-paste')">
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
      <NativeCustomerPicker v-if="invoiceIsLocal(form)" v-model="form.local_customer_id" :disabled="Boolean(form.id)" :selected-name="form.customer_name" @select="selectLocalCustomer" />
      <div v-else class="customer-filter-row">
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
      <div v-if="!invoiceIsLocal(form) && !okkiBound && privateOnlyCompany" class="binding-helper">
        {{ canTogglePrivate
          ? '未绑定 OKKI，私海筛选无结果。请取消“仅私海”或前往外部账号绑定。'
          : '未绑定 OKKI，暂无法搜索私海客户。请到 系统管理 → 外部账号绑定 处理。' }}
      </div>
      <InvoiceCustomerSyncEntry v-if="!invoiceIsLocal(form)" :on-select="selectSyncedCustomer" />
      <div v-if="customerRule" class="rule-badge">该客户价格规则：{{ describeCustomerRule(customerRule) }}</div>
    </el-form-item>
    <el-form-item label="客户等级" required>
      <el-select v-model="form.customer_grade" @change="markCustomerGradeTouched" placeholder="请选择等级" :disabled="!form.customer_id">
        <el-option v-for="grade in ['S', 'A', 'B', 'C', 'D', 'E']" :key="grade" :label="grade" :value="grade" />
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
    <div class="fgrid-c3 subdiv">订单信息</div>

    <div class="fgrid-c3 fgrid">
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
          class="invoice-no-gold"
          maxlength="64"
          placeholder="已自动生成，可修改"
          @input="onInvoiceNoInput"
          @blur="onInvoiceNoBlur"
        />
        <div v-if="previousInvoiceNo" class="prev-order-tip">该业务员上一张{{ orderTypeLabel(form.order_type) }}：{{ previousInvoiceNo }}</div>
      </el-form-item>
      <el-form-item label="下单日期" required>
        <el-date-picker v-model="form.invoice_date" value-format="YYYY-MM-DD" style="width: 100%" />
      </el-form-item>
      <el-form-item v-if="form.id" label="币种">
        <el-input v-model="form.currency" maxlength="16" @change="onCurrencyChange" />
      </el-form-item>
      <el-form-item v-if="!invoiceIsLocal(form)" label="小满标记" required class="fgrid-c3">
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
    <div class="fgrid-c3 contact-details-heading">
      <span>联系与收货信息{{ contactDetailsComplete ? '（已填写）' : '（待补全）' }}</span>
      <el-button v-if="contactDetailsComplete" link type="primary"
                 :aria-expanded="contactDetailsExpanded" @click="contactDetailsExpanded = !contactDetailsExpanded">
        {{ contactDetailsExpanded ? '收起联系与收货信息' : '展开联系与收货信息' }}
      </el-button>
    </div>
    <div v-show="contactDetailsExpanded || !contactDetailsComplete" class="fgrid-c3 fgrid">
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
  </div>
</section>
</template>

<script setup>
import NativeCustomerPicker from '../native/components/NativeCustomerPicker.vue'
import { invoiceIsLocal } from '@/views/commerce-transition/routeState'
function selectLocalCustomer(customer) {
  props.form.local_customer_id = customer?.id || null
  props.form.customer_id = customer ? `ark:${customer.id}` : ''
  props.form.customer_name = customer?.display_name || ''
}

import { DocumentCopy } from '@element-plus/icons-vue'
import { customerOptionLabel } from '../composables/useInvoiceCustomerSearch'
import { orderTypeLabel } from '../composables/useInvoiceShipments'
import { describeCustomerRule } from '../composables/useInvoiceEditor'
import InvoiceCustomerSyncEntry from './InvoiceCustomerSyncEntry.vue'

const selectedCustomer = defineModel('selectedCustomer')
const privateOnlyCompany = defineModel('privateOnlyCompany')
const contactDetailsExpanded = defineModel('contactDetailsExpanded', { default: true })

defineEmits(['open-whole-order-paste'])
const props = defineProps({
  form: { type: Object, required: true },
  contactDetailsComplete: Boolean,
  salesUserOptions: { type: Array, required: true },
  customerOptions: { type: Array, required: true },
  customerLoading: Boolean,
  customerTotal: Number,
  customerHasMore: Boolean,
  okkiBound: Boolean,
  canTogglePrivate: Boolean,
  customerRule: Object,
  lastOrderDate: String,
  invoiceNoTaken: Boolean,
  previousInvoiceNo: String,
  onSalesUserChange: { type: Function, required: true },
  searchCustomers: { type: Function, required: true },
  onCustomerChange: { type: Function, required: true },
  loadMoreCustomers: { type: Function, required: true },
  selectSyncedCustomer: { type: Function, required: true },
  markCustomerGradeTouched: { type: Function, required: true },
  onInvoiceNoInput: { type: Function, required: true },
  onInvoiceNoBlur: { type: Function, required: true },
  onCurrencyChange: { type: Function, required: true },
  markOkkiFlagTouched: { type: Function, required: true },
})
</script>

<style scoped>
.contact-details-heading {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 12px;
  color: var(--text-secondary);
  font-size: 13px;
}
</style>
