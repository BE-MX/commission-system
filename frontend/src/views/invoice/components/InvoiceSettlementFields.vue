<template>
  <section class="settlement-card">
    <div class="card-title">费用与结算</div>
    <div class="sgrid">
      <el-form-item label="付款方式" class="c2">
        <el-select v-model="form.internal_payment_method" clearable placeholder="请选择" @change="onPaymentMethodChange">
          <el-option v-for="option in paymentMethods" :key="option" :label="option" :value="option" />
        </el-select>
      </el-form-item>
      <el-form-item label="预付款" :error="settlementError">
        <el-input-number v-model="form.internal_received" :min="0" :max="total" :precision="2" controls-position="right" />
      </el-form-item>
      <el-form-item label="尾款">
        <el-input :model-value="form.internal_balance == null ? '' : money(form.internal_balance)" readonly class="balance-field" />
        <div class="field-hint">根据订单总额与预付款自动计算</div>
      </el-form-item>
      <el-form-item label="包装数量">
        <el-input-number v-model="form.packaging_quantity" :min="0" :precision="0" controls-position="right" />
      </el-form-item>
      <el-form-item label="包装费用">
        <el-input-number v-model="form.internal_accessory" :min="0" :precision="2" controls-position="right" />
      </el-form-item>
      <el-form-item label="运费">
        <el-input-number v-model="form.shipping_fee" :disabled="form.order_type === 'presale'" :min="0" :precision="2" controls-position="right" />
      </el-form-item>
      <el-form-item label="手续费" class="c2">
        <el-input-number
          v-model="form.surcharge_amount"
          :min="0"
          :precision="2"
          controls-position="right"
          @change="onHandlingFeeInput"
        />
        <div v-if="handlingHint" class="handling-hint">{{ handlingHint }}</div>
      </el-form-item>
      <!-- 总折扣：默认=产品行折扣合计；手改后均分到产品行，余数计入最后一行 -->
      <el-form-item label="折扣" class="c2">
        <el-input-number
          :model-value="totalDiscount"
          :min="0"
          :precision="2"
          controls-position="right"
          @change="onTotalDiscountChange"
        />
        <div class="field-hint">默认 = 产品明细折扣合计；修改后自动均分到各产品行，余数计入最后一行</div>
      </el-form-item>
    </div>
  </section>
</template>

<script setup>
import { computed, watch } from 'vue'
import { computeHandlingFee, handlingFeeRate } from '../composables/invoiceSettlement'

const props = defineProps({
  form: { type: Object, required: true },
  total: { type: Number, required: true },
  settlementError: { type: String, default: '' },
  paymentMethods: { type: Array, required: true },
  totalDiscount: { type: Number, default: 0 },
  money: { type: Function, required: true },
  onPaymentMethodChange: { type: Function, default: () => {} },
  onHandlingFeeInput: { type: Function, default: () => {} },
  onTotalDiscountChange: { type: Function, default: () => {} },
})

watch(() => props.form.order_type, type => { if (type === 'presale') props.form.shipping_fee = 0 }, { immediate: true })

// 手续费提示：比例方式显示自动费率；当前值与费率×基数不符时（如编辑单改了产品、
// 或手动改过）给出重算引导；报关提示手填，其余留空
const handlingHint = computed(() => {
  const method = props.form.internal_payment_method
  const rate = handlingFeeRate(method)
  if (rate == null) return method && method.includes('报关') ? '报关：手动填写手续费' : ''
  const pct = `${(rate * 100).toFixed(0)}%`
  // 基数（订单总金额，不含手续费）= 应付合计(total) − 手续费
  const base = Number(props.total || 0) - Number(props.form.surcharge_amount || 0)
  const expected = computeHandlingFee(rate, base)
  if (Math.abs(Number(props.form.surcharge_amount || 0) - expected) > 0.005) {
    return `与 ${pct}（应 ${expected.toFixed(2)}）不符，重选付款方式可重算`
  }
  return `${method} ${pct} 自动（可手改）`
})
</script>

<style scoped>
.settlement-card { display: block; }
.card-title { margin: 0 0 12px; font-size: 14px; font-weight: 700; color: var(--text-primary); }
/* 右栏窄宽：2 列小表单，标签顶部对齐由 el-form label-position 提供 */
.sgrid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 12px; align-items: start; }
.c2 { grid-column: 1 / -1; }
.sgrid :deep(.el-form-item__content) { width: 100%; min-width: 0; }
.sgrid :deep(.el-input-number) { width: 100%; }
.balance-field :deep(.el-input__wrapper) { background: var(--table-header-bg); }
.balance-field :deep(.el-input__inner) { font-variant-numeric: tabular-nums; }
.field-hint { margin-top: 2px; color: var(--text-muted); font-size: 11px; line-height: 1.3; }
.handling-hint { margin-top: 2px; color: var(--text-muted); font-size: 11px; line-height: 1.3; }
@media (max-width: 560px) { .sgrid { grid-template-columns: 1fr; } }
</style>
