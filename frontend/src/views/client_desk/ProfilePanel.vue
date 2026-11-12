<template>
  <div class="profile">
    <section class="panel summary">
      <div class="head"><h4>综合画像</h4><span class="muted">{{ generated }}</span></div>
      <p>{{ brief || '还没有 AI 画像。点击“重新分析”后，助理会综合订单、沟通、背调与跟进记录生成。' }}</p>
      <div class="coverage" aria-label="画像资料覆盖">
        <span v-for="item in coverageItems" :key="item.key" class="tag" :class="item.ok ? 'tone-success' : 'tone-neutral'">{{ item.label }}</span>
      </div>
    </section>
    <section v-for="block in profile?.blocks || []" :key="block.key" class="panel">
      <h4>{{ block.label }}</h4>
      <p>{{ block.text }}</p>
      <span class="cites"><button v-for="cite in block.cites" :key="cite.key" type="button" class="link-button" @click="$emit('evidence', cite.event_key)">{{ citeLabel(cite) }} ↘</button></span>
    </section>
    <section class="panel facts">
      <h4>已同步事实</h4>
      <dl>
        <div><dt>历史订单</dt><dd>{{ ordersText }}</dd></div>
        <div><dt>最近下单</dt><dd>{{ detail.last_order_date ? formatBeijingDate(detail.last_order_date) : '暂无' }}</dd></div>
        <div><dt>最近接触</dt><dd>{{ detail.personal_state?.last_touch_at ? formatBeijingShortDateTime(detail.personal_state.last_touch_at) : '暂无可见接触' }}</dd></div>
        <div><dt>联系人</dt><dd>{{ contacts }}</dd></div>
      </dl>
      <p v-for="gap in detail.coverage_gaps || []" :key="gap" class="muted">· {{ gap }}</p>
    </section>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { formatMoney } from '@/utils/money'
import { formatBeijingDate, formatBeijingShortDateTime } from '@/utils/datetime'

const props = defineProps({ detail: { type: Object, required: true } })
defineEmits(['evidence'])
const SOURCE_LABELS = { whatsapp: 'WhatsApp', order: '订单', research: '背调', followup: '跟进', alibaba_feed: '询盘', rule: '规则' }
const profile = computed(() => props.detail.profile)
const brief = computed(() => props.detail.brief_md || props.detail.personal_state?.brief_md)
const generated = computed(() => profile.value?.generated_at ? `生成于 ${formatBeijingShortDateTime(profile.value.generated_at)}` : '')
const coverageItems = computed(() => {
  const coverage = profile.value?.coverage || {}
  return [
    { key: 'orders', label: `订单 ${coverage.orders ?? 0}`, ok: coverage.orders > 0 },
    { key: 'messages', label: `WhatsApp ${coverage.messages ?? 0}`, ok: coverage.messages > 0 },
    { key: 'inquiries', label: `询盘 ${coverage.inquiries ?? 0}`, ok: coverage.inquiries > 0 },
    { key: 'research', label: coverage.research ? '背调已纳入' : '无背调', ok: !!coverage.research },
    { key: 'followups', label: `跟进 ${coverage.followups ?? 0}`, ok: coverage.followups > 0 },
  ]
})
const ordersText = computed(() => {
  const summary = props.detail.orders_summary || {}
  const money = formatMoney(summary.amount_usd, { currency: 'USD', missing: '金额待同步' })
  return `${summary.count ?? 0} 单 · ${money}${summary.unknown_amount_count ? `（${summary.unknown_amount_count} 笔金额待确认）` : ''}`
})
const contacts = computed(() => (props.detail.contacts || []).map(c => c.name).filter(Boolean).join('、') || '暂无')
function citeLabel(cite) { return SOURCE_LABELS[cite.source] || '来源' }
</script>

<style src="./board.css" scoped></style>
<style scoped>
.profile { display: grid; gap: 12px; }
.panel + .panel { margin-top: 0; }
.head { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; }
.summary { border-color: var(--tag-gold-border); }
p { margin: 0; line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; }
.coverage { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
dl { display: grid; gap: 8px; margin: 0 0 6px; }
dl > div { display: grid; grid-template-columns: 84px 1fr; gap: 10px; }
dt { color: var(--text-secondary); }
dd { margin: 0; font-weight: 600; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
</style>
