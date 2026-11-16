<template>
  <aside class="churn-panel" aria-label="需要处理的客户">
    <template v-if="!selected">
      <div class="churn-panel__head">
        <h3>{{ ship.state.focus ? `${ship.state.focus} · ` : '' }}需要处理的客户</h3>
        <p class="churn-muted">临界 {{ lists.critical.length }} · 预警 {{ lists.warning.length }}{{ canReadAll ? '' : ' · 仅我的客户' }}</p>
      </div>
      <div class="churn-panel__list">
        <template v-for="group in groups" :key="group.key">
          <div v-if="group.items.length" class="churn-group">{{ group.title }}</div>
          <button v-for="item in group.items" :key="item.id" type="button" class="churn-item" @click="$emit('select', item)">
            <i :class="['churn-dot', `is-${item.tier}`]" />
            <span class="churn-item__main">
              <span class="churn-item__name">{{ item.row.shop_name }}</span><span class="churn-tag">{{ item.level || '未定级' }}</span>
              <span class="churn-muted churn-item__meta">{{ metaOf(item) }}</span>
            </span>
            <b class="churn-item__days">{{ item.tier === 'fallen' ? `${daysAgo(item)} 天前` : item.remaining <= 0 ? '已超期' : `${Math.ceil(item.remaining)} 天` }}</b>
          </button>
        </template>
        <p v-if="!lists.critical.length && !lists.warning.length" class="churn-empty">这个范围内没有临界或预警客户</p>
      </div>
    </template>
    <template v-else>
      <div class="churn-panel__head is-row"><button type="button" class="churn-btn" @click="$emit('back')">‹ 返回清单</button></div>
      <div class="churn-detail">
        <h3>{{ row.shop_name }}</h3>
        <p class="churn-muted">{{ row.region }}{{ row.province ? ` · ${row.province}` : '' }} · {{ row.level || '未定级' }}</p>
        <template v-if="selected.tier === 'fallen'">
          <p class="churn-big">{{ daysAgo(selected) }}<small>{{ selected.fallen ? '天前落海' : '天前落海（推演）' }}</small></p>
          <dl v-if="row.previous_owner_name"><dt>原归属人</dt><dd>{{ row.previous_owner_name }}</dd></dl>
          <p v-if="canClaim && selected.fallen" class="churn-note">认领只重置跟进倒计时。超过 3 个月没下单的客户，认领后要尽快下单，否则下一次释放会再回到公海。</p>
        </template>
        <template v-else>
          <p v-if="selected.remaining > 0" :class="['churn-big', `is-${selected.tier}`]">{{ Math.ceil(selected.remaining) }}<small>天后释放入公海</small></p>
          <p v-else class="churn-big is-critical">{{ Math.floor(-selected.remaining) }}<small>天前已到期</small></p>
          <p v-if="selected.remaining <= 0" class="churn-note">{{ ruleNote }}</p>
          <p class="churn-muted">先到期的是{{ CLOCK_TEXT[row.clock] }}</p>
          <dl>
            <template v-if="canReadAll"><dt>归属人</dt><dd>{{ row.owner_name || '—' }}</dd>
              <dt>跟进负责人</dt><dd>{{ row.followup_name || '无跟进安排' }}</dd></template>
            <template v-else><dt>我的身份</dt><dd>{{ [row.mine_as_owner && '归属人', row.mine_as_followup && '跟进负责人'].filter(Boolean).join('、') || '—' }}</dd></template>
            <dt>上次跟进</dt><dd>{{ row.last_followup_date || '无记录' }}</dd>
            <dt>上次下单</dt><dd>{{ row.last_order_date || '无记录' }}</dd>
            <dt>跟进频率</dt><dd>{{ strapText }}</dd>
          </dl>
          <p class="churn-note">记一条跟进或下一单，跟进钟重新计 1 个月；订单钟只有下单才重置。</p>
        </template>
        <p v-if="ship.mode.value !== 'live'" class="churn-note">当前是{{ ship.mode.value === 'replay' ? '回放' : '推演' }}画面，回到今天后才能操作。</p>
        <div class="churn-acts">
          <template v-if="selected.tier === 'fallen'">
            <button v-if="canClaim && selected.fallen" type="button" class="churn-btn is-primary" :disabled="!live || claiming" @click="$emit('claim', selected)">{{ claiming ? '认领中…' : '认领' }}</button>
          </template>
          <template v-else>
            <button v-permission="'domestic_followup:write'" type="button" class="churn-btn is-primary" :disabled="!live" @click="$emit('record', { customer_id: row.id, shop_name: row.shop_name })">记一条跟进</button>
          </template>
          <button type="button" class="churn-btn" @click="$emit('timeline', row.id)">看时间线</button>
        </div>
      </div>
    </template>
    <div class="churn-legend">
      <span><i class="churn-dot is-stable" />稳固 &gt;14 天</span><span><i class="churn-dot is-warning" />预警 4–14 天</span>
      <span><i class="churn-dot is-critical" />临界 ≤3 天</span><span><i class="churn-dot is-fallen" />近 30 天已落海</span>
      <span>箱越大等级越高</span><span>绑带松开 = 已超跟进频率</span>
    </div>
  </aside>
</template>
<script setup>
import { computed } from 'vue'
import { CLOCK_TEXT } from './churnFormat'

const props = defineProps({ ship: { type: Object, required: true }, selected: { type: Object, default: null },
  canClaim: Boolean, claiming: Boolean, canReadAll: Boolean })
defineEmits(['select', 'back', 'record', 'timeline', 'claim'])
const lists = computed(() => props.ship.lists.value)
const groups = computed(() => [
  { key: 'critical', title: '临界 · 3 天内落海', items: lists.value.critical },
  { key: 'warning', title: '预警 · 4–14 天', items: lists.value.warning },
  { key: 'fallen', title: '近期已落海', items: lists.value.fallen },
])
const row = computed(() => props.selected?.row || {})
const live = computed(() => props.ship.mode.value === 'live')
const strapText = computed(() => ({ tight: '按频率跟上了', loose: `已超频率 ${row.value.frequency_overdue_days} 天`, none: '未定级或没有跟进安排' }[row.value.strap] || '—'))
function daysAgo(item) { return Math.max(0, Math.round(-item.remaining)) }
const ruleNote = computed(() => {
  const rule = props.ship.data.value?.rule || {}
  if (row.value.clock === 'follow' && !rule.follow_enforced) return '这是预演：「1 个月未跟进」规则生效后，这家会在当天被释放。'
  return '今天的释放任务跑完后会落海；现在记跟进或下单还来得及。'
})
function metaOf(item) {
  const r = item.row
  if (item.tier === 'fallen') return r.region
  const who = props.canReadAll && r.owner_name ? `${r.owner_name} · ` : ''
  return `${r.region} · ${who}${r.clock === 'follow' ? '跟进钟' : '订单钟'}`
}
</script>
