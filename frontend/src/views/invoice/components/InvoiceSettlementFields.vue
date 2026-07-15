<template>
  <section class="head-section settlement-section">
    <div class="col-title">费用与结算信息</div>
    <div class="head-grid">
      <el-form-item label="付款方式" class="span-2">
        <el-select v-model="form.internal_payment_method" clearable placeholder="请选择">
          <el-option v-for="option in paymentMethods" :key="option" :label="option" :value="option" />
        </el-select>
      </el-form-item>
      <el-form-item label="预付款" class="span-2" :error="settlementError">
        <el-input-number v-model="form.internal_received" :min="0" :max="total" :precision="2" controls-position="right" />
      </el-form-item>
      <el-form-item label="尾款" class="span-2">
        <el-input :model-value="form.internal_balance == null ? '' : money(form.internal_balance)" readonly class="balance-field">
          <template #append>根据订单总额与预付款自动计算</template>
        </el-input>
      </el-form-item>
      <el-form-item label="头发金额" class="span-2">
        <el-input :model-value="money(hairAmount)" readonly class="calculated-amount">
          <template #suffix><span class="amount-note">Hair Price</span></template>
        </el-input>
      </el-form-item>
      <el-form-item label="头发折扣" class="span-2 negative-field">
        <el-input :model-value="money(hairDiscount)" readonly class="calculated-amount">
          <template #suffix><span class="amount-note">Discount</span></template>
        </el-input>
      </el-form-item>
      <el-form-item label="配件金额" class="span-2">
        <el-input :model-value="money(accessoryAmount)" readonly class="calculated-amount" />
      </el-form-item>
      <el-form-item label="配件折扣" class="span-2 negative-field">
        <el-input :model-value="money(accessoryDiscount)" readonly class="calculated-amount" />
      </el-form-item>
      <el-form-item label="包装数量" class="span-1">
        <el-input-number v-model="form.packaging_quantity" :min="0" :precision="0" controls-position="right" />
      </el-form-item>
      <el-form-item label="包装费用" class="span-1">
        <el-input-number v-model="form.internal_accessory" :min="0" :precision="2" controls-position="right" />
      </el-form-item>
      <el-form-item label="快递渠道" class="span-2">
        <el-select v-model="form.express_channel" clearable placeholder="请选择">
          <el-option v-for="option in expressChannels" :key="option" :label="option" :value="option" />
        </el-select>
      </el-form-item>
      <el-form-item label="运费" class="span-2">
        <el-input-number v-model="form.shipping_fee" :min="0" :precision="2" controls-position="right" />
      </el-form-item>
      <el-form-item label="手续费" class="span-2">
        <el-input-number v-model="form.surcharge_amount" :min="0" :precision="2" controls-position="right" />
      </el-form-item>
    </div>
  </section>
</template>

<script setup>
defineProps({
  form: { type: Object, required: true },
  total: { type: Number, required: true },
  settlementError: { type: String, default: '' },
  hairAmount: { type: Number, required: true },
  hairDiscount: { type: Number, required: true },
  accessoryAmount: { type: Number, required: true },
  accessoryDiscount: { type: Number, required: true },
  paymentMethods: { type: Array, required: true },
  expressChannels: { type: Array, required: true },
  money: { type: Function, required: true },
})
</script>

<style scoped>
.head-section { max-width: 1400px; padding-bottom: 2px; margin: 18px 0 10px; border-bottom: 1px solid var(--border-color); }
.col-title { margin: 2px 0 10px; color: var(--text-secondary); font-size: 14px; font-weight: 700; }
.head-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 0 16px; align-items: start; }
.span-1 { grid-column: span 1; } .span-2 { grid-column: span 2; }
.head-grid :deep(.el-form-item__content) { width: 100%; min-width: 0; max-width: 360px; }
.span-1 :deep(.el-form-item__content) { max-width: 180px; }
.calculated-amount :deep(.el-input__wrapper) { background: var(--table-header-bg); }
.calculated-amount :deep(.el-input__inner), .negative-field :deep(input) { font-variant-numeric: tabular-nums; }
.negative-field :deep(input) { color: var(--color-danger); }
.amount-note { color: var(--text-muted); font-size: 11px; white-space: nowrap; }
.balance-field :deep(.el-input-group__append) { padding: 0 10px; color: var(--text-secondary); font-size: 11px; white-space: nowrap; }
@media (max-width: 1100px) { .head-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 900px) { .head-grid { grid-template-columns: 1fr; } .span-1, .span-2 { grid-column: 1 / -1; } }
@media (max-width: 560px) { .head-grid :deep(.el-form-item__content), .span-1 :deep(.el-form-item__content) { max-width: none; } }
</style>
