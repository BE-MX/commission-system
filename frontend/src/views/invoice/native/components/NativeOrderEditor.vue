<template>
  <el-dialog :model-value="modelValue" :title="amend ? '变更已确认订单' : invoice ? '编辑本地订单草稿' : '新建本地订单'"
    width="760px" :close-on-click-modal="!command.pending.value" :close-on-press-escape="!command.pending.value" :show-close="!command.pending.value"
    @update:model-value="$emit('update:modelValue', $event)">
    <ListPageStatus :error="options.errorMessage.value" :loading="options.loading.value" :has-data="options.hasData.value" :paged="false" @retry="options.load()" />
    <el-form ref="formRef" :model="form" label-position="top" :disabled="command.pending.value">
      <div class="form-grid">
        <el-form-item label="客户（必选）"><NativeCustomerPicker v-model="form.local_customer_id" :selected-name="form.customer_name" :disabled="amend || command.pending.value" @select="customer => form.customer_name = customer?.display_name || ''" /></el-form-item>
        <el-form-item label="归属业务员（必选）"><el-select v-model="form.sales_user_id" filterable :disabled="!!invoice" placeholder="选择业务员"><el-option v-for="user in assignees" :key="user.id" :value="user.id" :label="user.real_name || user.username" /></el-select></el-form-item>
        <el-form-item label="订单类型"><el-select v-model="form.order_type" :disabled="amend" @change="onTypeChange"><el-option v-for="(label, value) in orderTypes" :key="value" :label="label" :value="value" /></el-select></el-form-item>
        <el-form-item label="订单日期"><el-date-picker v-model="form.invoice_date" type="date" value-format="YYYY-MM-DD" :disabled="amend" /></el-form-item>
        <el-form-item label="订单编号（留空自动生成）"><el-input v-model="form.invoice_no" maxlength="56" :disabled="amend" /></el-form-item>
        <el-form-item label="币种（必选）"><el-select v-model="form.currency" :disabled="amend" filterable placeholder="选择币种"><el-option v-for="currency in currencies" :key="currency.code" :value="currency.code" :label="`${currency.code} · ${currency.name}`" /></el-select></el-form-item>
        <el-form-item label="跟单员（选填）"><el-select v-model="form.merchandiser_id" filterable clearable><el-option v-for="user in options.data.value?.merchandisers || []" :key="user.id" :value="user.id" :label="user.real_name || user.username" /></el-select></el-form-item>
        <el-form-item label="付款条款"><el-input v-model="form.payment_term" maxlength="256" /></el-form-item>
      </div>
      <h3>商品明细</h3>
      <fieldset v-for="(line, index) in form.items" :key="line.key" class="order-line">
        <legend>第 {{ index + 1 }} 行</legend>
        <el-form-item label="产品 / SKU"><SkuPicker v-model="line.local_sku_id" :selected-label="line.label" :disabled="command.pending.value || (amend && !!(line.stock_reserved_quantity || line.stock_shipped_quantity || line.production_pending_quantity))" @select="sku => line.label = sku?.label || ''" /></el-form-item>
        <div class="form-grid">
          <el-form-item label="数量（件）"><el-input-number v-model="line.quantity" :min="1" :max="2147483647" :precision="0" /></el-form-item>
          <el-form-item label="单价（最多四位小数）"><el-input v-model="line.price_per_piece" inputmode="decimal" maxlength="13" /></el-form-item>
          <el-form-item label="折扣金额（零或负数）"><el-input v-model="line.discount_amount" inputmode="decimal" maxlength="16" /></el-form-item>
          <el-form-item label="交易性质"><el-select v-model="line.commercial_kind"><el-option label="大货" value="bulk" /><el-option label="样品" value="sample" /></el-select></el-form-item>
        </div>
        <GlassButton v-if="form.items.length > 1" variant="link" left-icon="Delete" link-tone="danger" :disabled="command.pending.value" @click="form.items.splice(index, 1)">移除明细</GlassButton>
      </fieldset>
      <GlassButton left-icon="Plus" :disabled="command.pending.value || form.items.length >= 200" @click="form.items.push(newOrderLine())">添加商品</GlassButton>
      <h3>合同费用</h3>
      <div class="form-grid">
        <el-form-item label="运费"><el-input v-model="form.shipping_fee" inputmode="decimal" :disabled="form.order_type === 'presale'" maxlength="15" /></el-form-item>
        <el-form-item label="附加费名称"><el-input v-model="form.surcharge_name" maxlength="128" /></el-form-item>
        <el-form-item label="附加费金额"><el-input v-model="form.surcharge_amount" inputmode="decimal" maxlength="15" /></el-form-item>
        <el-form-item label="包装 / 配件费用"><el-input v-model="form.internal_accessory" inputmode="decimal" maxlength="15" /></el-form-item>
        <el-form-item label="包装数量"><el-input-number v-model="form.packaging_quantity" :min="0" :max="2147483647" :precision="0" /></el-form-item>
      </div>
      <div v-if="form.order_type === 'presale'" class="form-grid">
        <el-form-item label="约定首款总额"><el-input v-model="form.local_deposit_amount" inputmode="decimal" maxlength="15" /></el-form-item>
        <el-form-item label="首款内含费用"><el-input v-model="form.local_deposit_charge" inputmode="decimal" maxlength="15" /></el-form-item>
      </div>
      <p class="amount-summary">商品金额 {{ formatNativeMoney(preview?.goods) }} · 合同总额 {{ formatNativeMoney(preview?.total) }} {{ form.currency }}（以保存后服务端结果为准）</p>
      <el-collapse>
        <el-collapse-item title="联系与配送信息" name="contact">
          <div class="form-grid"><el-form-item label="联系人"><el-input v-model="form.contact_name" maxlength="256" /></el-form-item><el-form-item label="联系电话"><el-input v-model="form.contact_phone" maxlength="100" /></el-form-item><el-form-item label="联系邮箱"><el-input v-model="form.contact_email" maxlength="256" /></el-form-item><el-form-item label="快递渠道"><el-input v-model="form.express_channel" maxlength="64" /></el-form-item></div>
          <el-form-item label="配送地址"><el-input v-model="form.delivery_address" type="textarea" maxlength="4000" /></el-form-item>
        </el-collapse-item>
        <el-collapse-item title="经营标记与部门分摊" name="commercial">
          <div class="form-grid">
            <el-form-item label="客户来源"><el-select v-model="form.commercial_source" :disabled="amend"><el-option v-for="(label, value) in commercialSources" :key="value" :label="label" :value="value" /></el-select></el-form-item>
            <el-form-item label="新客成交"><el-select v-model="form.is_new_deal" :disabled="amend"><el-option label="未标记" value=""/><el-option label="是" :value="true"/><el-option label="否" :value="false"/></el-select></el-form-item>
            <el-form-item label="首次返单"><el-select v-model="form.is_first_return" :disabled="amend"><el-option label="未标记" value=""/><el-option label="是" :value="true"/><el-option label="否" :value="false"/></el-select></el-form-item>
            <el-form-item label="私域订单"><el-switch v-model="form.is_private_order" :disabled="amend" /></el-form-item>
          </div>
          <p>不填写分摊时，确认订单按业务员名册的销售部门归属。已确认订单的经营标记不能覆盖。</p>
          <div v-for="(share, index) in form.department_allocations" :key="index" class="form-grid">
            <el-form-item label="部门"><el-select v-model="share.department_id" filterable :disabled="amend"><el-option v-for="department in options.data.value?.departments || []" :key="department.id" :value="department.id" :label="department.name" /></el-select></el-form-item>
            <el-form-item label="比例（%）"><el-input v-model="share.rate" :disabled="amend" inputmode="decimal" maxlength="8" /></el-form-item>
            <GlassButton v-if="!amend" variant="link" left-icon="Delete" :disabled="command.pending.value" @click="form.department_allocations.splice(index, 1)">移除此部门</GlassButton>
          </div>
          <GlassButton v-if="!amend" left-icon="Plus" :disabled="command.pending.value || form.department_allocations.length >= 50" @click="form.department_allocations.push({ department_id: null, rate: '' })">添加分摊部门</GlassButton>
        </el-collapse-item>
      </el-collapse>
      <el-form-item label="订单备注"><el-input v-model="form.remark" type="textarea" maxlength="4000" /></el-form-item>
      <template v-if="amend">
        <p>已确认订单的客户、币种、类型、业务员、原始日期及编号保持不变。有履约事实的明细由后端限制变更。</p>
        <div class="form-grid"><el-form-item label="变更业务日期"><el-date-picker v-model="form.business_date" type="date" value-format="YYYY-MM-DD" /></el-form-item><el-form-item label="补充供货仓库（按需）"><el-select v-model="form.warehouse_id" clearable filterable><el-option v-for="w in options.data.value?.warehouses || []" :key="w.id" :label="w.name" :value="w.id" /></el-select></el-form-item></div>
        <el-form-item label="变更原因（必填）"><el-input v-model="form.reason" type="textarea" maxlength="500" /></el-form-item>
      </template>
    </el-form>
    <el-alert v-if="command.failure.value" type="error" :title="command.failure.value" :closable="false" show-icon />
    <p v-if="command.failure.value">输入已保留。内容不变重试沿用原请求；遇版本冲突请关闭后刷新订单，核对最新内容再编辑。</p>
    <template #footer><div class="dialog-footer"><GlassButton :disabled="command.pending.value" @click="$emit('update:modelValue', false)">取消</GlassButton><GlassButton v-permission="'invoice:write'" variant="primary" :loading="command.pending.value" :disabled="options.loading.value || !!options.error.value" @click="save">{{ amend ? '提交订单变更' : '保存草稿' }}</GlassButton></div></template>
  </el-dialog>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { getNativeInvoiceReference, getNativeAssignees, getNativeMerchandisers, createNativeInvoice, updateNativeInvoice, amendNativeInvoice } from '@/api/nativeInvoice'
import { getDepartments } from '@/api/trade'
import { msgSuccess, confirmDanger } from '@/utils/feedback'
import { useNativeCommand } from '@/views/finance/native/useNativeCommand'
import { formatNativeMoney, orderPreview } from '@/views/finance/native/decimal'
import SkuPicker from '@/views/inventory/components/SkuPicker.vue'
import NativeCustomerPicker from './NativeCustomerPicker.vue'
import { makeOrderDraft, newOrderLine, draftPayload } from '../draft'
import { orderTypes, commercialSources } from '../labels'
const props = defineProps({ modelValue: Boolean, invoice: Object, amend: Boolean })
const emit = defineEmits(['update:modelValue', 'saved'])
const auth = useAuthStore(), command = useNativeCommand(), formRef = ref()
const form = ref(makeOrderDraft())
const options = useAsyncResource(async (_, { signal }) => {
  const config = { signal, suppressToast: true }
  const [reference, users, merchandisers, departments] = await Promise.all([getNativeInvoiceReference(config), getNativeAssignees(config), getNativeMerchandisers(config), getDepartments(config)])
  return { ...reference.data, assignees: users.data.items, merchandisers: merchandisers.data.items, departments: departments.data }
})
const preview = computed(() => orderPreview(form.value))
const assignees = computed(() => {
  const rows = [...(options.data.value?.assignees || [])]
  if (props.invoice?.sales_user_id && !rows.some(r => r.id === props.invoice.sales_user_id)) rows.unshift({ id: props.invoice.sales_user_id, real_name: props.invoice.sales_user_name })
  return rows
})
const currencies = computed(() => {
  const rows = (options.data.value?.currencies || []).filter(c => c.active !== false)
  if (props.invoice?.currency && !rows.some(c => c.code === props.invoice.currency)) return [{ code: props.invoice.currency, name: '原订单币种' }, ...rows]
  return rows
})
watch(form, command.reset, { deep: true, flush: 'sync' })
watch(() => props.modelValue, async visible => {
  if (!visible) return
  form.value = makeOrderDraft(props.invoice)
  command.reset()
  if (await options.load()) {
    if (!form.value.sales_user_id) form.value.sales_user_id = assignees.value.find(u => u.id === Number(auth.user?.id))?.id || (assignees.value.length === 1 ? assignees.value[0].id : null)
    if (!form.value.currency && currencies.value.length === 1) form.value.currency = currencies.value[0].code
  }
})
function onTypeChange() { if (form.value.order_type === 'presale') form.value.shipping_fee = '0'; else { form.value.local_deposit_amount = '0'; form.value.local_deposit_charge = '0' } }
async function save() {
  const result = await command.run({
    validate: () => formRef.value.validate().catch(() => false),
    payload: () => ({ ...draftPayload(form.value, props.amend), expected_authority_epoch: props.invoice?.authority_epoch }),
    confirm: props.amend ? () => confirmDanger('变更订单', props.invoice.invoice_no, '将同步调整未履约库存责任及应收，历史凭证保留。') : undefined,
    send: body => props.amend ? amendNativeInvoice(props.invoice.id, body) : props.invoice ? updateNativeInvoice(props.invoice.id, body) : createNativeInvoice(body),
  })
  if (result.ok) { msgSuccess(props.amend ? '变更订单' : '保存草稿'); emit('update:modelValue', false); emit('saved', result.data) }
}
</script>
<style scoped>
.form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 0 16px; }
.form-grid .el-select, .form-grid .el-date-editor { width: 100%; }
.order-line { padding: 16px; margin: 0 0 16px; border: 1px solid var(--border-color); border-radius: 8px; }
.order-line legend, p { color: var(--text-secondary); }
.amount-summary { padding: 12px; background: var(--page-bg); font-variant-numeric: tabular-nums; }
</style>
