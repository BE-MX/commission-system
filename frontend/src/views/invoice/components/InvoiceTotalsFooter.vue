<template>
  <div class="drawer-footer">
    <!-- 逐项金额（头发/配件/折扣等）在右栏「金额汇总」卡实时展示，这里只保留合计口径 -->
    <div class="total-box">
      <span class="summary-chip base">订单总金额 <strong>{{ form.currency }} {{ money(baseAmount) }}</strong></span>
      <span class="summary-divider">·</span>
      <span class="summary-chip handling">手续费 <strong>{{ money(form.surcharge_amount) }}</strong><em class="chip-note">仅方舟记录</em></span>
      <span class="summary-operator">→</span>
      <span class="summary-chip total">应付合计 <strong>{{ form.currency }} {{ money(total) }}</strong></span>
    </div>
    <div class="footer-controls">
      <p v-if="blockedReason" class="footer-note" role="status">{{ blockedReason }}</p>
      <div class="footer-actions">
        <el-button @click="$emit('cancel')">取消</el-button>
        <!-- 无同步权限时「保存」升为主按钮，避免抽屉底部没有主操作 -->
        <el-button v-permission="'invoice:write'" :type="canSync && !writeBlocked ? '' : 'primary'" :disabled="writeBlocked" @click="$emit('save')">保存</el-button>
        <el-tooltip :disabled="!writeBlocked" :content="blockedReason">
          <span>
            <el-button v-permission="'invoice:sync'" type="primary" :disabled="writeBlocked" :loading="syncing" @click="$emit('sync')">
              {{ syncing ? '保存并同步中' : '保存并同步' }}
            </el-button>
          </span>
        </el-tooltip>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth'

const props = defineProps({
  form: { type: Object, required: true },
  total: { type: Number, required: true },
  baseAmount: { type: Number, required: true },
  money: { type: Function, required: true },
  syncing: { type: Boolean, default: false },
  syncBlocked: { type: Boolean, default: false },
  syncBlockedReason: { type: String, default: '' },
})
defineEmits(['cancel', 'save', 'sync'])

const canSync = computed(() => useAuthStore().hasPermission('invoice:sync'))
const writeBlocked = computed(() => props.syncBlocked || Boolean(props.form.presale_edit_blocked_reason))
const blockedReason = computed(() => props.form.presale_edit_blocked_reason || (props.syncBlocked ? props.syncBlockedReason : ''))
</script>

<style scoped>
.drawer-footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 10px 0 2px; }
.total-box { display: flex; min-width: 0; flex: 1; align-items: baseline; flex-wrap: wrap; gap: 6px; color: var(--text-secondary); font-variant-numeric: tabular-nums; }
.summary-chip { display: inline-flex; min-height: 30px; align-items: center; gap: 5px; padding: 4px 9px; border-radius: 8px; background: var(--invoice-summary-bg); color: var(--text-secondary); white-space: nowrap; }
.summary-chip strong { color: var(--invoice-summary-fg); font-weight: 700; }
.handling { --invoice-summary-fg: var(--invoice-summary-handling-fg); --invoice-summary-bg: var(--invoice-summary-handling-bg); }
.base { --invoice-summary-fg: var(--invoice-summary-total-fg); --invoice-summary-bg: var(--invoice-summary-total-bg); padding-inline: 12px; }
.base strong { font-size: 15px; }
.total { --invoice-summary-fg: var(--invoice-summary-total-fg); --invoice-summary-bg: var(--invoice-summary-total-bg); padding-inline: 12px; font-size: 14px; }
.total strong { font-size: 17px; }
.summary-operator { color: var(--text-secondary); }
.summary-divider { color: var(--text-muted); }
.chip-note { margin-left: 5px; color: var(--text-muted); font-size: 11px; font-style: normal; }
.footer-actions { display: flex; flex-shrink: 0; gap: 8px; }
.footer-controls { display: flex; flex-direction: column; align-items: flex-end; gap: 8px; max-width: 480px; }
.footer-note { margin: 0; color: var(--text-secondary); font-size: 12px; line-height: 1.6; }
@media (max-width: 900px) { .drawer-footer { align-items: stretch; flex-direction: column; } }
</style>
