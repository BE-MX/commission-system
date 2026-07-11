<template>
  <aside class="decision-panel">
    <div class="panel-head">
      <div><span class="eyebrow">AI · SOP DECISION SUPPORT</span><h2>分析与处理建议</h2></div>
      <GlassButton v-if="!locked" variant="secondary" left-icon="MagicStick" :loading="analyzing" @click="$emit('analyze')">{{ latestAi || caseData.current_status === 'ai_failed' ? '重新分析' : '开始分析' }}</GlassButton>
    </div>

    <div v-if="analyzing" class="analysis-progress">
      <el-icon class="is-loading"><Loading /></el-icon>
      <div><strong>正在生成建议</strong><span>检查证据 → 匹配 SOP → 生成方案与英文话术</span></div>
    </div>
    <div v-else-if="caseData.current_status === 'ai_failed'" class="analysis-error">
      <strong>AI 分析失败</strong><span>可以重新分析，或直接填写人工建议继续处理。</span>
    </div>

    <template v-if="latestAi || caseData.responsibility_class || caseData.current_status === 'ai_failed'">
      <div class="result-block">
        <div class="block-label">责任判定</div>
        <div v-if="latestAi" class="ai-original">AI 建议：<strong>{{ latestAi.responsibility?.class }} 类 · {{ latestAi.responsibility?.label }}</strong><span>{{ Math.round((latestAi.responsibility?.confidence || 0) * 100) }}% 置信度</span></div>
        <el-select v-model="responsibility" :disabled="locked" placeholder="业务员确认责任分类">
          <el-option v-for="item in responsibilityOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-input v-model="responsibilityReason" :disabled="locked" type="textarea" :rows="2" placeholder="填写责任判断理由；人工方案请注明 SOP 条款或“无适用条款”" />
        <el-input v-if="latestAi && responsibility && responsibility !== latestAi.responsibility?.class" v-model="overrideReason" :disabled="locked" type="textarea" :rows="2" placeholder="修改 AI 判定时必须说明原因" />
      </div>

      <div v-if="latestAi?.sop_citations?.length" class="result-block citations">
        <div class="block-label">SOP 引用</div>
        <div v-for="(citation, index) in latestAi.sop_citations" :key="index" class="citation-card">
          <strong>{{ citation.section }} · {{ citation.clause }}</strong><span>{{ citation.quote_digest }}</span>
        </div>
      </div>

      <div class="result-block">
        <div class="block-label">选择处理措施</div>
        <el-select v-model="actionCodes" multiple :disabled="locked" placeholder="可组合多个措施">
          <el-option v-for="item in options.actions || []" :key="item.code" :label="item.label" :value="item.code" />
        </el-select>
        <div v-for="action in actions" :key="action.code" class="action-detail">
          <strong>{{ actionLabel(action.code) }}</strong>
          <div class="action-fields">
            <template v-if="action.code === 'care_guidance'"><el-input v-model="action.care_plan" :disabled="locked" type="textarea" :rows="2" placeholder="填写给客户的护理方案" /></template>
            <template v-else-if="action.code === 'return_inspection'">
              <el-input v-model="action.return_address" :disabled="locked" placeholder="退回地址" />
              <el-select v-model="action.freight_payer" :disabled="locked" placeholder="运费承担方"><el-option label="客户承担" value="customer" /><el-option label="公司承担" value="company" /></el-select>
              <el-date-picker v-model="action.expected_completion_date" :disabled="locked" type="date" value-format="YYYY-MM-DD" placeholder="预计完成日" />
              <el-input-number v-if="action.freight_payer === 'company'" v-model="action.freight_cost_usd" :disabled="locked" :min="0" :precision="2" placeholder="公司承担运费 USD" />
            </template>
            <template v-else-if="action.code === 'paid_rework'">
              <el-input-number v-model="action.service_fee_usd" :disabled="locked" :min="0" :precision="2" placeholder="处理费 USD" />
              <el-select v-model="action.freight_payer" :disabled="locked" placeholder="运费承担方"><el-option label="客户承担" value="customer" /><el-option label="公司承担" value="company" /></el-select>
              <el-input-number v-if="action.freight_payer === 'company'" v-model="action.freight_cost_usd" :disabled="locked" :min="0" :precision="2" placeholder="公司承担运费 USD" />
            </template>
            <template v-else-if="action.code === 'free_rework'">
              <el-input-number v-model="action.estimated_cost_usd" :disabled="locked" :min="0" :precision="2" placeholder="处理成本 USD" />
              <el-input-number v-model="action.freight_cost_usd" :disabled="locked" :min="0" :precision="2" placeholder="运费 USD" />
            </template>
            <template v-else-if="['replacement', 'resend'].includes(action.code)">
              <el-input-number v-model="action.quantity" :disabled="locked" :min="0.01" :precision="2" placeholder="数量" />
              <el-input v-model="action.product" :disabled="locked" placeholder="产品与规格" />
              <el-input-number v-model="action.estimated_cost_usd" :disabled="locked" :min="0" :precision="2" placeholder="估算成本 USD" />
              <el-input-number v-if="action.code === 'resend'" v-model="action.freight_cost_usd" :disabled="locked" :min="0" :precision="2" placeholder="运费 USD" />
              <el-date-picker v-model="action.delivery_date" :disabled="locked" type="date" value-format="YYYY-MM-DD" placeholder="预计交付日期" />
            </template>
            <template v-else-if="action.code === 'cash_refund'">
              <el-input-number v-model="action.amount_usd" :disabled="locked" :min="0" :precision="2" placeholder="退款金额" /><el-select v-model="action.currency" :disabled="locked"><el-option label="USD" value="USD" /><el-option label="CNY" value="CNY" /></el-select>
            </template>
            <template v-else-if="action.code === 'discount'">
              <el-input-number v-model="action.discount_percent" :disabled="locked" :min="0" :max="100" :precision="2" placeholder="折扣比例 %" /><el-input-number v-model="action.amount_usd" :disabled="locked" :min="0" :precision="2" placeholder="或折扣金额 USD" /><el-input v-model="action.applicable_order" :disabled="locked" placeholder="适用订单" />
            </template>
            <template v-else-if="action.code === 'order_credit'">
              <el-input-number v-model="action.amount_usd" :disabled="locked" :min="0" :precision="2" placeholder="抵扣金额 USD" /><el-date-picker v-model="action.expiry_date" :disabled="locked" type="date" value-format="YYYY-MM-DD" placeholder="有效期" />
            </template>
            <template v-else-if="action.code === 'freight_subsidy'">
              <el-input-number v-model="action.amount_usd" :disabled="locked" :min="0" :precision="2" placeholder="补贴金额" /><el-select v-model="action.currency" :disabled="locked"><el-option label="USD" value="USD" /><el-option label="CNY" value="CNY" /></el-select>
            </template>
            <template v-else-if="action.code === 'custom'">
              <el-input v-model="action.description" :disabled="locked" placeholder="说明自定义措施" /><el-switch v-model="action.company_bears_cost" :disabled="locked" active-text="公司承担成本" /><el-input-number v-if="action.company_bears_cost" v-model="action.estimated_cost_usd" :disabled="locked" :min="0" :precision="2" placeholder="估算成本 USD" />
            </template>
            <span v-else class="unit">该措施无需额外执行字段</span>
          </div>
        </div>
      </div>

      <div v-if="caseData.has_compensation" class="compensation-summary">
        <span>预计赔偿总成本</span><strong>USD {{ caseData.estimated_compensation_usd || '0.00' }}</strong>
        <span>问题货值 USD {{ caseData.affected_goods_value }} · 占比 {{ ratio }}</span>
      </div>

      <div class="result-block reply-block">
        <div class="reply-head"><div><div class="block-label">英文客户回复话术</div><span>AI 基于 SOP 生成，发送前由业务员确认</span></div><GlassButton variant="secondary" left-icon="CopyDocument" :disabled="!copyable" @click="$emit('copy-reply')">{{ copyable ? '复制话术' : '审批后可复制' }}</GlassButton></div>
        <el-input v-model="reply" :disabled="locked" type="textarea" :rows="9" maxlength="8000" show-word-limit />
        <div v-if="replyError" class="reply-error">{{ replyError }}</div>
      </div>
    </template>

    <div v-else class="empty-analysis"><el-icon><MagicStick /></el-icon><strong>先完成登记，再生成 SOP 建议</strong><span>系统会输出证据判断、责任分类、措施和英文客户话术。</span></div>
  </aside>
</template>

<script setup>
import { computed } from 'vue'
import { canCopyReply, compensationRatio, validateEnglishReply } from '../aftersalesRules'

const props = defineProps({
  caseData: { type: Object, required: true }, latestAi: { type: Object, default: null }, options: { type: Object, default: () => ({}) },
  locked: Boolean, analyzing: Boolean, actions: { type: Array, default: () => [] }, replyDraft: { type: String, default: '' },
  responsibilityClass: { type: String, default: '' }, responsibilityReason: { type: String, default: '' }, overrideReason: { type: String, default: '' },
})
const emit = defineEmits(['analyze', 'copy-reply', 'update:actions', 'update:reply-draft', 'update:responsibility-class', 'update:responsibility-reason', 'update:override-reason'])
const valueCodes = new Set(['free_rework', 'replacement', 'resend', 'cash_refund', 'discount', 'order_credit', 'freight_subsidy'])
const responsibilityOptions = [
  { value: 'A', label: 'A 类 · 明确生产/包装/批次问题' }, { value: 'B', label: 'B 类 · 产品特性或正常范围' },
  { value: 'C', label: 'C 类 · 使用/存储/护理原因' }, { value: 'D', label: 'D 类 · 责任暂不明确' },
]
const responsibility = computed({ get: () => props.responsibilityClass, set: value => emit('update:responsibility-class', value) })
const responsibilityReason = computed({ get: () => props.responsibilityReason, set: value => emit('update:responsibility-reason', value) })
const overrideReason = computed({ get: () => props.overrideReason, set: value => emit('update:override-reason', value) })
const reply = computed({ get: () => props.replyDraft, set: value => emit('update:reply-draft', value) })
const actionCodes = computed({
  get: () => props.actions.map(item => item.code),
  set: codes => emit('update:actions', codes.map(code => ({ ...defaultAction(code), ...(props.actions.find(item => item.code === code) || {}) }))),
})
const copyable = computed(() => canCopyReply(props.caseData.current_status))
const ratio = computed(() => compensationRatio(props.caseData.estimated_compensation_usd, props.caseData.affected_goods_value))
const hasCompensation = computed(() => props.actions.some(item => valueCodes.has(item.code) || (['return_inspection', 'paid_rework'].includes(item.code) && item.freight_payer === 'company') || (item.code === 'custom' && item.company_bears_cost)))
const replyError = computed(() => validateEnglishReply(hasCompensation.value, reply.value))
function actionLabel(code) { return props.options.actions?.find(item => item.code === code)?.label || code }
function defaultAction(code) {
  const defaults = { code }
  if (['cash_refund', 'freight_subsidy'].includes(code)) defaults.currency = 'USD'
  if (['return_inspection', 'paid_rework'].includes(code)) defaults.freight_payer = 'customer'
  if (['replacement', 'resend'].includes(code)) {
    defaults.quantity = Number(props.caseData.quantity || 1)
    defaults.product = props.caseData.product_name_snapshot || ''
  }
  if (code === 'custom') defaults.company_bears_cost = false
  return defaults
}
</script>

<style scoped>
.decision-panel { padding: 18px; border: 1px solid var(--border-color); border-radius: var(--card-radius); background: var(--card-bg); box-shadow: var(--card-shadow); }
.panel-head, .reply-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }.eyebrow { color: var(--color-gold-muted); font: 700 10px/1.2 var(--font-display); letter-spacing: .12em; }.panel-head h2 { margin: 4px 0 0; color: var(--text-primary); font: 700 17px/1.3 var(--font-display); }
.analysis-progress, .analysis-error, .empty-analysis { display: flex; gap: 10px; padding: 14px; margin-top: 16px; border-radius: 10px; }.analysis-progress { color: var(--color-info-text); background: var(--color-info-bg); }.analysis-error { flex-direction: column; color: var(--color-danger-text); background: var(--color-danger-bg); }.analysis-progress div, .empty-analysis { display: flex; flex-direction: column; }.analysis-progress span, .empty-analysis span { margin-top: 3px; color: var(--text-secondary); font-size: 12px; }
.result-block { padding-top: 16px; margin-top: 16px; border-top: 1px solid var(--border-color); }.block-label { margin-bottom: 8px; color: var(--text-secondary); font: 700 12px/1.3 var(--font-display); text-transform: uppercase; letter-spacing: .06em; }.ai-original { display: flex; flex-wrap: wrap; gap: 6px 10px; padding: 10px; margin-bottom: 10px; border-radius: 8px; background: var(--toolbar-bg); color: var(--text-secondary); font-size: 12px; }.ai-original strong { color: var(--text-primary); }.result-block :deep(.el-select) { width: 100%; }.result-block :deep(.el-textarea) { margin-top: 10px; }
.citation-card { display: flex; flex-direction: column; gap: 4px; padding: 10px; border-left: 3px solid var(--color-primary); background: var(--color-gold-soft); font-size: 12px; }.citation-card + .citation-card { margin-top: 8px; }.citation-card span { color: var(--text-secondary); }
.action-detail { display: grid; grid-template-columns: minmax(120px, .45fr) minmax(0, 1.55fr); gap: 10px; align-items: start; padding: 10px; margin-top: 8px; border: 1px solid var(--border-color); border-radius: 8px; }.action-detail > strong { padding-top: 8px; }.action-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }.action-fields :deep(.el-input), .action-fields :deep(.el-input-number), .action-fields :deep(.el-select), .action-fields :deep(.el-date-editor) { width: 100%; }.unit { color: var(--text-muted); font-size: 11px; }
.compensation-summary { display: grid; gap: 4px; padding: 14px; margin-top: 16px; border: 1px solid var(--color-gold-muted); border-radius: 10px; background: var(--color-gold-soft); }.compensation-summary strong { color: var(--text-primary); font-size: 22px; font-variant-numeric: tabular-nums; }.compensation-summary span { color: var(--text-secondary); font-size: 12px; }
.reply-head span { color: var(--text-muted); font-size: 11px; }.reply-error { margin-top: 8px; color: var(--color-danger-text); font-size: 12px; }.empty-analysis { align-items: center; text-align: center; color: var(--text-secondary); background: var(--toolbar-bg); }
@media (max-width: 760px) { .action-detail, .action-fields { grid-template-columns: 1fr; }.panel-head, .reply-head { flex-direction: column; } }
</style>
