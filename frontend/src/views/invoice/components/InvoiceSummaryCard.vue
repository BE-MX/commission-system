<template>
  <!-- 金额汇总：头发/配件金额与折扣等自动计算项的只读展示，随明细实时联动；
       可输入的结算字段在「费用与结算」卡，不在此重复 -->
  <section class="summary-card">
    <div class="card-title">
      金额汇总
      <span class="hint">随明细实时联动</span>
    </div>
    <div class="sum-rows">
      <div class="sum-row">
        <span class="k"><i class="dotk hair" />头发金额</span>
        <span class="v">{{ money(hairAmount) }}</span>
      </div>
      <div class="sum-row neg">
        <span class="k"><i class="dotk hair-discount" />头发折扣</span>
        <span class="v">{{ money(hairDiscount) }}</span>
      </div>
      <div class="sum-row">
        <span class="k"><i class="dotk accessory" />配件金额</span>
        <span class="v">{{ money(accessoryAmount) }}</span>
      </div>
      <div class="sum-row neg">
        <span class="k"><i class="dotk accessory-discount" />配件折扣</span>
        <span class="v">{{ money(accessoryDiscount) }}</span>
      </div>
      <div class="sum-row">
        <span class="k"><i class="dotk packaging" />包装费用（{{ form.packaging_quantity || 0 }} 件）</span>
        <span class="v">{{ money(form.internal_accessory) }}</span>
      </div>
      <div class="sum-row">
        <span class="k"><i class="dotk shipping" />运费</span>
        <span class="v">{{ money(form.shipping_fee) }}</span>
      </div>
      <div class="sum-div" />
      <div class="sum-base">
        <span>订单总金额</span>
        <span class="v">{{ form.currency }} {{ money(baseAmount) }}</span>
      </div>
      <div class="sum-row">
        <span class="k"><i class="dotk handling" />手续费<small class="note">仅方舟记录</small></span>
        <span class="v">{{ money(form.surcharge_amount) }}</span>
      </div>
      <div class="sum-total">
        <span class="k">应付合计</span>
        <span class="v">{{ form.currency }} {{ money(total) }}</span>
      </div>
    </div>
  </section>
</template>

<script setup>
defineProps({
  form: { type: Object, required: true },
  total: { type: Number, required: true },
  baseAmount: { type: Number, required: true },
  hairAmount: { type: Number, required: true },
  hairDiscount: { type: Number, required: true },
  accessoryAmount: { type: Number, required: true },
  accessoryDiscount: { type: Number, required: true },
  money: { type: Function, required: true },
})
</script>

<style scoped>
.card-title { display: flex; align-items: baseline; gap: 10px; margin: 0 0 12px; font-size: 14px; font-weight: 700; color: var(--text-primary); }
.card-title .hint { font-size: 12px; font-weight: 400; color: var(--text-muted); }
.sum-rows { display: flex; flex-direction: column; gap: 7px; }
.sum-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; font-size: 13px; color: var(--text-secondary); }
.sum-row .k { display: flex; align-items: center; gap: 8px; min-width: 0; }
.sum-row .v { font-weight: 600; color: var(--text-primary); font-variant-numeric: tabular-nums; }
.sum-row.neg .v { color: var(--color-danger); }
.dotk { width: 8px; height: 8px; border-radius: 3px; flex: none; }
.dotk.hair { background: var(--invoice-summary-hair-fg); }
.dotk.hair-discount { background: var(--invoice-summary-hair-discount-fg); }
.dotk.accessory { background: var(--invoice-summary-accessory-fg); }
.dotk.accessory-discount { background: var(--invoice-summary-accessory-discount-fg); }
.dotk.packaging { background: var(--invoice-summary-packaging-fg); }
.dotk.shipping { background: var(--invoice-summary-shipping-fg); }
.dotk.handling { background: var(--invoice-summary-handling-fg); }
.note { margin-left: 5px; color: var(--text-muted); font-size: 11px; }
.sum-div { height: 1px; margin: 3px 0; background: var(--border-warm); }
.sum-base { display: flex; align-items: baseline; justify-content: space-between; font-size: 13.5px; font-weight: 600; color: var(--text-primary); }
.sum-base .v { font-size: 15px; font-variant-numeric: tabular-nums; }
.sum-total {
  display: flex; align-items: baseline; justify-content: space-between;
  margin-top: 7px; padding: 10px 12px; border-radius: 10px;
  background: var(--invoice-summary-total-bg); border: 1px solid rgba(212, 148, 28, 0.35);
}
.sum-total .k { font-size: 13.5px; font-weight: 700; color: var(--invoice-summary-total-fg); }
.sum-total .v { font-size: 19px; font-weight: 800; color: var(--invoice-summary-total-fg); font-variant-numeric: tabular-nums; }
</style>
