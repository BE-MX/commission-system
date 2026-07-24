<template>
  <div class="drawer-footer">
    <div class="total-box">
      <span class="summary-chip hair">头发金额 <strong>{{ money(hairAmount) }}</strong></span>
      <span class="summary-operator">+</span>
      <span class="summary-chip hair-discount">头发折扣 <strong>{{ money(hairDiscount) }}</strong></span>
      <span class="summary-operator">+</span>
      <span class="summary-chip accessory">配件金额 <strong>{{ money(accessoryAmount) }}</strong></span>
      <span class="summary-operator">+</span>
      <span class="summary-chip accessory-discount">配件折扣 <strong>{{ money(accessoryDiscount) }}</strong></span>
      <span class="summary-operator">+</span>
      <span class="summary-chip packaging">包装费用 <strong>{{ money(form.internal_accessory) }}</strong> · {{ form.packaging_quantity }} 件</span>
      <span class="summary-operator">+</span>
      <span class="summary-chip shipping">运费 <strong>{{ money(form.shipping_fee) }}</strong></span>
      <span class="summary-operator">=</span>
      <span class="summary-chip base">订单总金额 <strong>{{ form.currency }} {{ money(baseAmount) }}</strong></span>
      <span class="summary-divider">·</span>
      <span class="summary-chip handling">手续费 <strong>{{ money(form.surcharge_amount) }}</strong><em class="chip-note">OKKI 侧扣减</em></span>
      <span class="summary-operator">→</span>
      <span class="summary-chip total">应付合计 <strong>{{ form.currency }} {{ money(total) }}</strong></span>
    </div>
    <div class="footer-actions">
      <el-button @click="$emit('cancel')">取消</el-button>
      <!-- 无同步权限时「保存」升为主按钮，避免抽屉底部没有主操作 -->
      <el-button v-permission="'invoice:write'" :type="canSync ? '' : 'primary'" @click="$emit('save')">保存</el-button>
      <el-button v-permission="'invoice:sync'" type="primary" @click="$emit('sync')">保存并同步</el-button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth'

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
defineEmits(['cancel', 'save', 'sync'])

const canSync = computed(() => useAuthStore().hasPermission('invoice:sync'))
</script>

<style scoped>
.drawer-footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 10px 0 2px; }
.total-box { display: flex; min-width: 0; flex: 1; align-items: baseline; flex-wrap: wrap; gap: 6px; color: var(--text-secondary); font-variant-numeric: tabular-nums; }
.summary-chip { display: inline-flex; min-height: 30px; align-items: center; gap: 5px; padding: 4px 9px; border-radius: 8px; background: var(--invoice-summary-bg); color: var(--text-secondary); white-space: nowrap; }
.summary-chip strong { color: var(--invoice-summary-fg); font-weight: 700; }
.hair { --invoice-summary-fg: var(--invoice-summary-hair-fg); --invoice-summary-bg: var(--invoice-summary-hair-bg); }
.hair-discount { --invoice-summary-fg: var(--invoice-summary-hair-discount-fg); --invoice-summary-bg: var(--invoice-summary-hair-discount-bg); }
.accessory { --invoice-summary-fg: var(--invoice-summary-accessory-fg); --invoice-summary-bg: var(--invoice-summary-accessory-bg); }
.accessory-discount { --invoice-summary-fg: var(--invoice-summary-accessory-discount-fg); --invoice-summary-bg: var(--invoice-summary-accessory-discount-bg); }
.packaging { --invoice-summary-fg: var(--invoice-summary-packaging-fg); --invoice-summary-bg: var(--invoice-summary-packaging-bg); }
.shipping { --invoice-summary-fg: var(--invoice-summary-shipping-fg); --invoice-summary-bg: var(--invoice-summary-shipping-bg); }
.handling { --invoice-summary-fg: var(--invoice-summary-handling-fg); --invoice-summary-bg: var(--invoice-summary-handling-bg); }
.base { --invoice-summary-fg: var(--invoice-summary-total-fg); --invoice-summary-bg: var(--invoice-summary-total-bg); padding-inline: 12px; }
.base strong { font-size: 15px; }
.total { --invoice-summary-fg: var(--invoice-summary-total-fg); --invoice-summary-bg: var(--invoice-summary-total-bg); padding-inline: 12px; font-size: 14px; }
.total strong { font-size: 17px; } .summary-operator { color: var(--text-secondary); }
.summary-divider { color: var(--text-muted); }
.chip-note { margin-left: 5px; color: var(--text-muted); font-size: 11px; font-style: normal; }
.footer-actions { display: flex; flex-shrink: 0; gap: 8px; }
@media (max-width: 900px) { .drawer-footer { align-items: stretch; flex-direction: column; } }
</style>
