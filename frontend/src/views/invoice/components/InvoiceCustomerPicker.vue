<template>
  <div class="invoice-customer-picker">
    <el-select
      :model-value="modelValue" value-key="option_key" filterable remote reserve-keyword
      :remote-method="search" :loading="loading" :disabled="checking || !active"
      placeholder="输入客户名称、ID 或联系人姓名" class="customer-select"
      popper-class="invoice-customer-options" :popper-options="{ strategy: 'fixed' }"
      @change="choose"
    >
      <el-option-group v-for="group in groups" :key="group.company_id" :label="group.company_name">
        <template #default>
          <li class="customer-group-heading" role="presentation">
            <div class="customer-group-name">{{ group.company_name }}<span v-if="group.country_name">{{ group.country_name }}</span></div>
            <div class="customer-group-meta">客户编号 {{ group.company_id }}</div>
          </li>
          <el-option
            v-for="row in group.options" :key="customerOptionKey(row)" :label="customerOptionLabel(row)" :value="row"
            :class="{ 'customer-contact-option': row.kind === 'contact' }"
          >
            <span class="customer-option-name">{{ row.kind === 'contact' ? row.name : '选择此客户' }}</span>
            <span class="customer-option-kind">{{ row.kind === 'contact' ? '联系人' : '客户' }}</span>
          </el-option>
        </template>
      </el-option-group>
      <template #footer>
        <div class="customer-picker-footer">
          <span>{{ hasMore ? '已加载' : '当前' }} {{ groups.length }} 位客户<span v-if="contactCount"> · {{ contactCount }} 位联系人</span></span>
          <el-button v-if="hasMore" link type="primary" :loading="loading" @click="loadMore">加载更多</el-button>
        </div>
      </template>
    </el-select>
    <div v-if="checking || error" class="customer-picker-feedback" :class="{ 'has-error': error }" role="status" aria-live="polite">
      {{ checking ? '正在核对小满客户…' : error }}
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, watch } from 'vue'
import { verifyInvoiceCustomer } from '@/api/invoice'
import { customerOptionKey, customerOptionLabel, groupCustomerOptions, useVerifiedCustomerSelection } from '../composables/useInvoiceCustomerSearch'

const props = defineProps({
  modelValue: { type: Object, default: null },
  options: { type: Array, default: () => [] },
  loading: Boolean,
  hasMore: Boolean,
  privateOnly: Boolean,
  salesUserId: Number,
  contextKey: String,
  active: { type: Boolean, default: true },
  search: { type: Function, required: true },
  loadMore: { type: Function, required: true },
})
const emit = defineEmits(['update:modelValue', 'change'])
const selection = useVerifiedCustomerSelection({
  current: () => props.modelValue,
  verify: row => verifyInvoiceCustomer({ customer_id: String(row.company_id), private_only: props.privateOnly, sales_user_id: props.salesUserId }),
  onSelect: row => { emit('update:modelValue', row); emit('change', row) },
})
const { checking, error, isUnavailable, choose } = selection
const groups = computed(() => groupCustomerOptions(props.options.filter(row => !isUnavailable(row.company_id))))
const contactCount = computed(() => groups.value.reduce((count, group) => count + group.options.filter(row => row.kind === 'contact').length, 0))
watch(() => [props.contextKey, props.privateOnly, props.salesUserId, props.active], selection.reset, { flush: 'sync' })
watch(() => props.modelValue, selection.cancel, { flush: 'sync' })
onBeforeUnmount(selection.cancel)
</script>

<style scoped>
.invoice-customer-picker { width: 100%; min-width: 0; }
.customer-select { width: 100%; }
.customer-picker-feedback { margin-top: 6px; color: var(--text-secondary); font-size: 12px; line-height: 1.5; }
.customer-picker-feedback.has-error { color: var(--color-warning-text); }
</style>

<style>
.invoice-customer-options { max-width: calc(100vw - 24px); }
.invoice-customer-options .el-select-group__title { display: none; }
.invoice-customer-options .customer-group-heading { padding: 10px 16px 6px; line-height: 1.5; }
.invoice-customer-options .customer-group-name { display: flex; flex-wrap: wrap; gap: 4px 10px; color: var(--text-primary); font-size: 13px; font-weight: 600; overflow-wrap: anywhere; }
.invoice-customer-options .customer-group-name > span { color: var(--text-secondary); font-size: 12px; font-weight: 400; }
.invoice-customer-options .customer-group-meta { display: flex; flex-wrap: wrap; gap: 4px 10px; color: var(--text-muted); font-size: 11px; }
.invoice-customer-options .el-select-dropdown__item { display: flex; align-items: center; justify-content: space-between; gap: 16px; height: auto; min-height: 34px; line-height: 1.5; padding: 6px 16px; white-space: normal; }
.invoice-customer-options .customer-contact-option { padding-left: 30px; }
.invoice-customer-options .customer-option-name { overflow-wrap: anywhere; min-width: 0; }
.invoice-customer-options .customer-option-kind { color: var(--text-secondary); font-size: 11px; flex-shrink: 0; font-weight: 400; }
.invoice-customer-options .customer-picker-footer { display: flex; align-items: center; flex-wrap: wrap; justify-content: space-between; gap: 8px; color: var(--text-secondary); font-size: 12px; }
</style>
