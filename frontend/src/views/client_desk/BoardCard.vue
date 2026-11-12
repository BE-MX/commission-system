<template>
  <div class="card" :class="{ compact, selected }" :style="{ '--strip': strip }">
    <span v-if="card.todo" class="pip" :title="card.todo_reasons?.join('；') || '今日待处理'" />
    <div class="top">
      <span class="avatar" aria-hidden="true">{{ initials(card.name) }}</span>
      <div class="ident">
        <div class="name">{{ card.name || '未命名客户' }}</div>
        <div class="sub">{{ [card.country, card.contact_name].filter(Boolean).join(' · ') || '国家与联系人待同步' }}</div>
      </div>
    </div>
    <div class="tags">
      <span v-for="tag in visibleTags" :key="tag.code" class="tag" :class="['tone-' + tagTone(tag), { solid: tag.kind === 'grade' && tag.code !== 'grade:none' }]">
        <template v-if="tag.kind === 'ai' || tag.kind === 'risk'">✦ </template>{{ tag.label }}
      </span>
      <span v-if="hiddenCount" class="tag">+{{ hiddenCount }}</span>
    </div>
    <div class="metrics">
      <span><b>{{ card.orders?.count ?? 0 }}</b> 单</span>
      <span><b>{{ amount }}</b></span>
      <span>{{ touchText }}</span>
    </div>
    <div v-if="!compact" class="foot">{{ card.todo_reasons?.[0] ? `今日：${card.todo_reasons[0]}` : (card.okki_stage ? `OKKI 阶段：${card.okki_stage}` : '暂无今日事项') }}</div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { formatMoney } from '@/utils/money'
import { beijingCalendarDaysUntil } from '@/utils/datetime'
import { initials, tagTone } from './boardModel'

const props = defineProps({
  card: { type: Object, required: true },
  compact: { type: Boolean, default: false },
  selected: { type: Boolean, default: false },
  maxTags: { type: Number, default: 5 },
})
const STRIPS = { S: 'var(--tag-gold-solid)', A: 'var(--tag-warning-solid)', B: 'var(--tag-info-solid)', C: 'var(--tag-success-solid)' }
const strip = computed(() => STRIPS[props.card.grade] || 'var(--tag-neutral-border)')
// Grade first, then stage, risk, AI; channel last because it rarely drives a decision.
const ORDER = { grade: 0, stage: 1, risk: 2, ai: 3, type: 4, channel: 5 }
const sortedTags = computed(() => [...(props.card.tags || [])].sort((a, b) => (ORDER[a.kind] ?? 9) - (ORDER[b.kind] ?? 9)))
const visibleTags = computed(() => sortedTags.value.slice(0, props.maxTags))
const hiddenCount = computed(() => Math.max(0, sortedTags.value.length - props.maxTags))
const amount = computed(() => formatMoney(props.card.orders?.amount_usd, { currency: 'USD', precision: 0, missing: '—', currencyDisplay: 'narrowSymbol' }))
const touchText = computed(() => {
  if (!props.card.last_touch_at) return '暂无可见接触'
  const days = -beijingCalendarDaysUntil(String(props.card.last_touch_at).slice(0, 10))
  return days <= 0 ? '今天联系' : `${days} 天前联系`
})
</script>

<style src="./board.css" scoped></style>
<style scoped>
.card { position: relative; display: block; width: 100%; padding: 11px 12px 10px 15px; overflow: hidden; border: 1px solid var(--border-color); border-radius: 13px; background: var(--card-bg); color: var(--text-primary); text-align: left; font-family: var(--font-body); transition: transform 250ms ease, box-shadow 250ms ease, border-color 250ms ease; }
.card::before { content: ""; position: absolute; inset: 0 auto 0 0; width: 4px; background: var(--strip); }
.card.selected { border-color: var(--color-primary); box-shadow: 0 0 0 2px var(--button-focus); }
.top { display: flex; align-items: center; gap: 9px; }
.ident { min-width: 0; }
.name { overflow: hidden; font: 650 14px/1.3 var(--font-display); text-overflow: ellipsis; white-space: nowrap; }
.sub { overflow: hidden; color: var(--text-secondary); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.tags { display: flex; flex-wrap: wrap; gap: 4px; max-height: 44px; margin: 8px 0 7px; overflow: hidden; }
.metrics { display: flex; gap: 10px; color: var(--text-secondary); font-size: 11px; font-variant-numeric: tabular-nums; }
.metrics b { color: var(--text-primary); font-weight: 600; }
.foot { margin-top: 8px; padding-top: 7px; overflow: hidden; border-top: 1px dashed var(--border-color); color: var(--text-secondary); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.pip { position: absolute; top: 10px; right: 10px; width: 8px; height: 8px; border-radius: 50%; background: var(--tag-danger-solid); box-shadow: 0 0 0 3px var(--tag-danger-bg); }
.compact { height: 132px; box-shadow: 0 6px 16px var(--xk-shadow); }
</style>
