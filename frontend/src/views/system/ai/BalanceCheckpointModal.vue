<template>
  <el-dialog
    :model-value="modelValue"
    :title="`登记余额 · ${target?.name || ''}`"
    width="480px"
    append-to-body
    destroy-on-close
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <p class="cp-intro">截点默认精确到当前时刻（北京时间），仅扣减该时刻之后结束的按量调用，避免重复扣减。</p>
    <el-form label-position="top" :model="form">
      <el-row :gutter="12">
        <el-col :span="12">
          <el-form-item label="登记类型">
            <el-select v-model="form.checkpoint_kind" class="w-full">
              <el-option label="余额核对" value="reconcile" />
              <el-option label="充值入账" value="topup" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="币种">
            <el-select v-model="form.balance_currency" class="w-full">
              <el-option label="人民币 (CNY)" value="CNY" />
              <el-option label="美元 (USD)" value="USD" />
            </el-select>
          </el-form-item>
        </el-col>
      </el-row>
      <el-row :gutter="12">
        <el-col :span="12">
          <el-form-item label="当前账户余额" required>
            <el-input-number v-model="form.balance_amount" :min="0" :precision="2" :step="10" class="w-full" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="生效截点（北京时间）">
            <el-date-picker
              v-model="form.recorded_at"
              type="datetime"
              value-format="YYYY-MM-DD HH:mm:ss"
              format="YYYY-MM-DD HH:mm"
              placeholder="默认提交时刻"
              class="w-full"
            />
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="备注（可选）">
        <el-input v-model="form.remark" maxlength="256" placeholder="如：官网核对 / 充值单号" />
      </el-form-item>
    </el-form>

    <div class="cp-diff-box">{{ diffPreview }}</div>

    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="saving" :disabled="form.balance_amount == null" @click="submit">
        保存流水
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, watch } from 'vue'
import { formatMoney } from '@/utils/money'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  target: { type: Object, default: null },
  saving: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'submit'])

const SYM = { CNY: '¥', USD: '$' }

const form = reactive({
  checkpoint_kind: 'reconcile',
  balance_amount: 0,
  balance_currency: 'CNY',
  recorded_at: '',
  remark: '',
})

watch(
  () => [props.modelValue, props.target],
  ([open, target]) => {
    if (!open || !target) return
    form.checkpoint_kind = 'reconcile'
    form.balance_currency = target.balance?.currency || target.billing?.price_currency || 'CNY'
    form.balance_amount = target.balance?.estimated_amount != null ? Number(target.balance.estimated_amount) : 0
    // 留空由后端在提交瞬间打北京时间截点，避免弹窗停留期间完成的调用被重复扣减
    form.recorded_at = ''
    form.remark = ''
  },
  { immediate: true },
)

const diffPreview = computed(() => {
  const cur = form.balance_currency
  const sym = SYM[cur] || `${cur} `
  const est = props.target?.balance?.estimated_amount
  if (est == null || props.target?.balance?.currency !== cur) {
    return '本次登记将作为新的余额估算起点与进度条 100% 基准。'
  }
  const diff = Number(form.balance_amount || 0) - Number(est)
  const sign = diff >= 0 ? '+' : ''
  return `当前系统估算：${sym}${formatMoney(est, 2)} · 登记差额：${sign}${sym}${formatMoney(diff, 2)}（将记入流水便于漂移复盘）`
})

function submit() {
  emit('submit', {
    checkpoint_kind: form.checkpoint_kind,
    balance_amount: Number(form.balance_amount),
    balance_currency: form.balance_currency,
    recorded_at: form.recorded_at ? form.recorded_at.replace(' ', 'T') : null,
    remark: form.remark.trim() || null,
  })
}
</script>

<style scoped>
.w-full { width: 100%; }
.cp-intro { margin: 0 0 14px; font-size: 12px; color: var(--text-muted); line-height: 1.5; }
.cp-diff-box {
  padding: 9px 12px; border-radius: 8px;
  background: var(--tag-neutral-bg); color: var(--text-secondary); font-size: 12px;
}
</style>
