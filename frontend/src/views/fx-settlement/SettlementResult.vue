<template>
  <section class="result-panel lg-card is-static" aria-label="结汇测算结果" aria-live="polite">
    <div v-if="!result" class="empty-result">
      <span class="eyebrow">YOUR SETTLEMENT PLAN</span>
      <h3>先守住用款，再比较结汇时机</h3>
      <p>填写资金条件，查看现在应结多少、最多还能留多少，以及美元涨跌对你的实际影响。</p>
      <ol><li>扣除必须保留的美元</li><li>覆盖立即需要的人民币</li><li>比较压力情景与分批计划</li></ol>
      <p class="muted">AI 会基于本次行情和测算选择方案；行情刷新不会自动触发 AI 调用。</p>
    </div>
    <template v-else>
      <p v-if="stale" class="notice" role="status">条件或报价已变化，以下是旧快照。请重新测算后再作判断。</p>
      <div class="result-heading"><div><span class="eyebrow">{{ result.selection_source === 'ai' ? 'AI 推荐 · 受资金约束' : '规则测算 · 尚非 AI 分析' }}</span><h3>{{ selected.label }}</h3></div><span class="stamp">{{ formatBeijingDateTime(result.generated_at, { seconds: false }) }}</span></div>
      <p v-if="result.ai" class="ai-summary">{{ result.ai.summary }}</p>
      <p v-else class="muted">先覆盖人民币需求，在所设压力情景内控制等待金额。该方案不保证收益最大。</p>
      <p v-if="result.ai_error" class="notice">{{ result.ai_error }}</p>
      <div class="allocation">
        <div><span>建议现在结汇</span><strong>${{ money(selected.now_usd) }}</strong><p>约 ¥{{ money(selected.now_cny) }}</p></div>
        <div><span>后续分批结汇</span><strong>${{ money(selected.later_usd) }}</strong><p>另预留美元 ${{ money(result.reserved_usd) }}</p></div>
      </div>
      <div class="risk-line">压力情景下，比全部现在结汇少得 <strong>¥{{ money(selected.stress_loss_cny) }}</strong>；你填写的预算为 ¥{{ money(result.input.max_loss_cny) }}。</div>
      <p class="muted">测算汇率 {{ result.rate.toFixed(4) }} · {{ result.rate_source }} · 报价时间 {{ formatBeijingDateTime(result.rate_at) }}</p>
      <ul v-if="result.warnings.length" class="warnings"><li v-for="warning in result.warnings" :key="warning">{{ warning }}</li></ul>

      <div v-if="result.ai" class="ai-details">
        <h4>为什么选择这个方案</h4><ul><li v-for="reason in result.ai.reasons" :key="reason">{{ reason }}</li></ul>
        <h4>这些变化出现时，重新判断</h4><ul><li v-for="point in result.ai.watchpoints" :key="point">{{ point }}</li></ul>
      </div>
      <h4>三个方案，同一口径比较</h4>
      <p class="muted">预计人民币总额包含即时结汇及等待部分，以最晚结汇日为比较时点；情景不是预测。</p>
      <div class="table-wrap"><table><thead><tr><th>方案</th><th>现在结汇 USD</th><th>跌 {{ result.input.stress_drop_pct }}%</th><th>持平</th><th>涨 {{ result.input.stress_drop_pct }}%</th></tr></thead><tbody><tr v-for="candidate in result.candidates" :key="candidate.id" :class="{ selected: candidate.id === selected.id }"><th>{{ candidate.label }}{{ candidate.id === selected.id ? ' ✓' : '' }}</th><td>{{ money(candidate.now_usd) }}</td><td v-for="scenario in candidate.scenarios" :key="scenario.label">¥{{ money(scenario.total_cny) }}</td></tr></tbody></table></div>
      <div class="scenario-cards">
        <article v-for="candidate in result.candidates" :key="candidate.id" :class="{ selected: candidate.id === selected.id }">
          <div class="candidate-heading"><h4>{{ candidate.label }}</h4><span v-if="candidate.id === selected.id">当前方案</span></div>
          <p>现在结汇 <strong>${{ money(candidate.now_usd) }}</strong></p>
          <dl><div v-for="(scenario, index) in candidate.scenarios" :key="scenario.label"><dt>{{ index === 0 ? `跌 ${result.input.stress_drop_pct}%` : index === 1 ? '持平' : `涨 ${result.input.stress_drop_pct}%` }}</dt><dd>¥{{ money(scenario.total_cny) }}</dd></div></dl>
        </article>
      </div>
      <template v-if="selected.schedule.length"><h4>后续分批日期</h4><div class="schedule"><div v-for="item in selected.schedule" :key="item.date"><span>{{ item.date }}</span><strong>${{ money(item.usd) }}</strong></div></div></template>
      <details><summary>查看计算假设与数据口径</summary><ul><li v-for="assumption in result.assumptions" :key="assumption">{{ assumption }}</li></ul><p>趋势：{{ result.market.trend?.as_of || '不可用' }}；行情检查：{{ formatBeijingDateTime(result.market.checked_at) }}。可等待本金上限为 ${{ money(result.maximum_later_usd) }}。</p></details>
    </template>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { formatBeijingDateTime } from '@/utils/datetime'
const props = defineProps({ result: Object, stale: Boolean })
const selected = computed(() => props.result?.candidates.find(row => row.id === props.result.selected_id))
const money = value => Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
</script>

<style scoped>
.result-panel { padding: 24px; min-width: 0; align-self: start; }
.eyebrow { color: var(--color-primary-hover); font: 700 11px var(--font-display); letter-spacing: .08em; }
h3 { margin: 8px 0 12px; font-size: 23px; }h4 { font-size: 14px; margin: 24px 0 10px; }
p,li { font-size: 13px; line-height: 1.7; }ul,ol { padding-left: 20px; }li+li { margin-top: 7px; }
.empty-result { padding: 28px 10px; }.empty-result ol { margin: 28px 0; }.empty-result li { padding: 6px 0; }
.muted,.stamp { color: var(--text-secondary); font-size: 12px; }.stamp { white-space: nowrap; }
.result-heading { display: flex; gap: 12px; align-items: center; justify-content: space-between; flex-wrap: wrap; }
.ai-summary { font-size: 15px; font-weight: 500; }.allocation { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; padding: 20px 0; border-block: 1px solid var(--border-color); margin: 20px 0 14px; }
.allocation span { color: var(--text-secondary); font-size: 12px; }.allocation strong { display: block; font: 700 27px var(--font-display); font-variant-numeric: tabular-nums; margin-top: 8px; overflow-wrap: anywhere; }.allocation p { margin: 5px 0; color: var(--text-secondary); }
.risk-line { font-size: 13px; }.notice,.warnings { padding: 12px 16px; background: var(--color-warning-bg); color: var(--color-warning-text); border-radius: 8px; font-size: 12px; }.warnings { padding-left: 30px; }
.table-wrap { overflow-x: auto; }table { border-collapse: collapse; width: 100%; font-size: 12px; font-variant-numeric: tabular-nums; }th,td { padding: 11px 9px; text-align: right; border-bottom: 1px solid var(--border-color); white-space: nowrap; }th:first-child { text-align: left; }thead th { color: var(--text-secondary); font-weight: 500; }.selected { background: var(--color-primary-light); }
.schedule { display: flex; flex-wrap: wrap; gap: 12px; }.schedule>div { flex: 1; min-width: 125px; border-left: 2px solid var(--color-primary); padding-left: 12px; }.schedule span { display: block; color: var(--text-secondary); font-size: 12px; }.schedule strong { font-size: 16px; font-variant-numeric: tabular-nums; }
details { margin-top: 24px; border-top: 1px solid var(--border-color); padding-top: 16px; font-size: 12px; color: var(--text-secondary); }summary { cursor: pointer; }
.scenario-cards { display: none; }
@media(max-width:800px) {
  .table-wrap { display: none; }
  .scenario-cards { display: grid; gap: 12px; }
  .scenario-cards article { border: 1px solid var(--border-color); border-radius: 12px; padding: 14px; min-width: 0; }
  .scenario-cards .selected { border-color: var(--color-primary); }
  .candidate-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .candidate-heading h4 { margin: 0; }
  .candidate-heading span { font-size: 11px; color: var(--color-primary-hover); }
  .scenario-cards dl { display: grid; gap: 10px; margin: 0; font-size: 13px; }
  .scenario-cards dl>div { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px; }
  .scenario-cards dt { color: var(--text-secondary); }
  .scenario-cards dd { margin: 0; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
  summary { min-height: 44px; display: flex; align-items: center; }
}
@media(max-width:600px) { .result-panel { padding: 18px; }.allocation { grid-template-columns: 1fr; gap: 16px; }.allocation strong { font-size: 26px; } }
</style>
