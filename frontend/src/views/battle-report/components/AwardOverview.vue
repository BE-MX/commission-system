<template>
  <div class="award-overview">
    <el-alert v-if="!data.data_complete" type="error" :closable="false" title="战报数据待核对，暂停排名与奖励判定" :description="data.issues.join('；')" />
    <el-alert v-if="data.period_state === 'upcoming'" type="info" :closable="false" title="活动尚未开始，当前展示参赛配置，未来订单不提前计入" />
    <template v-if="data.award_kind === 'annual_repurchase'">
      <p class="award-note">美元目标直接引用Excel“评比需满足最低门槛”列，2026年OKKI美元GMV与该目标直接比较，不换汇、不重新分档或推算目标。</p>
      <div class="award-summary"><div><span>已达GMV门槛</span><strong>{{ data.qualified.length }}<small> / {{ data.people.length }}人</small></strong></div><div><span>参评席位</span><strong>TOP 5</strong></div><p>新签客户 × 20% + 当年新签复购客户 × 20% + 美元复购金额 ÷ 5000 × 60%</p></div>
      <el-alert v-if="data.cutoff_tie" type="warning" :closable="false" title="第五名边界存在同分，待确认决胜规则；同分人员不预判获奖" />
      <section v-for="group in groups" :key="group.key"><h3>{{ group.label }} <span>{{ group.rows.length }}人</span></h3><el-empty v-if="!group.rows.length" description="暂无人员" :image-size="60" />
        <div v-else class="award-people"><article v-for="row in group.rows" :key="row.member_id" :class="['award-person', { 'award-top': row.top_five }]">
          <header><span>{{ row.rank ? `候选第${row.rank}名` : row.overall_rank ? `总榜第${row.overall_rank}名` : '排名待核对' }}</span><StatusBadge v-if="row.top_five" type="warning">前五名候选</StatusBadge></header>
          <h4>{{ row.user_name }} <b>{{ data.data_complete ? number(row.score, 4) : '待核对' }}<small> 系数</small></b></h4>
          <p>当前GMV {{ row.gmv_complete ? `$${number(row.gmv)}` : '待核对' }} / 美元门槛 {{ row.target === null ? '待确认' : `$${number(row.target)}` }}</p>
          <el-progress :percentage="row.gmv_complete && row.progress_percent !== null ? Math.min(100, row.progress_percent) : 0" :show-text="false" :status="row.qualified ? 'success' : undefined" />
          <p><strong>{{ row.gmv_complete && row.progress_percent !== null ? `${number(row.progress_percent, 1)}%` : '进度待核对' }}</strong> · 2025基数 ${{ number(row.baseline) }} · 目标来源：Excel最低门槛列</p>
          <footer v-if="data.data_complete">新签 {{ row.new_count }} 客户 · 复购 {{ row.repeat_count }} 客户 / {{ row.repeat_orders }} 笔 · 复购 ${{ number(row.repeat_amount) }}</footer><footer v-else>新签、复购客户数、复购笔数及金额待核对</footer>
        </article></div>
      </section>
    </template>
    <template v-else>
      <header class="pk-heading"><h3>11月新签对决</h3><p>{{ data.pk_status }}</p></header>
      <div class="pk-arena"><article v-for="(team, index) in data.teams" :key="team.team" :class="['pk-team', { 'pk-leading': team.leading }]">
        <header><h3>{{ team.team }}</h3><StatusBadge :type="team.leading ? 'warning' : 'info'">{{ team.leading ? '当前领先' : '全力追赶' }}</StatusBadge></header>
        <p class="pk-captain">队长 · {{ team.captain }}</p><div class="pk-count">{{ team.new_count }}<small>{{ data.data_complete ? '' : '（已核实至少）' }} / {{ team.target }}个新签</small></div>
        <el-progress :percentage="Math.min(100, team.progress_percent)" :show-text="false" :status="team.completed ? 'success' : undefined" /><p v-if="data.data_complete">目标完成 {{ number(team.progress_percent, 1) }}% · {{ team.completed ? '已达标' : `还差${Math.max(0, team.target - team.new_count)}个` }}</p><p v-else>达标状态、完成进度与奖励待核对</p>
        <dl v-if="data.data_complete"><div><dt>人均新签</dt><dd>{{ number(team.new_count / team.member_count, 2) }}个</dd></div><div><dt>人均新签金额</dt><dd>${{ number(Number(team.new_amount) / team.member_count) }}</dd></div><div><dt>人均月GMV</dt><dd>${{ number(Number(team.gmv) / team.member_count) }}</dd></div></dl>
        <div class="pk-roster"><div v-for="person in team.people" :key="person.member_id"><strong>{{ person.user_name }} <StatusBadge v-if="person.is_captain" type="warning" size="small">队长</StatusBadge></strong><b>{{ person.new_count }}<small> {{ data.data_complete ? '个新签' : '个（已核实至少）' }}</small></b></div></div>
        <footer v-if="data.data_complete">目标奖金 ¥{{ team.target_bonus }} · PK奖金 ¥{{ team.pk_bonus }} · 队长询盘 {{ team.inquiries }}个<br />{{ data.rewards_provisional ? '当前为奖励预测，活动结束后确认' : '按当前数据计算，奖金与询盘尚未发放' }}</footer><footer v-else>目标奖金、PK奖金及队长询盘均待核对</footer>
      </article><span class="pk-vs" aria-label="对阵">VS</span></div>
      <p class="award-note">每人目标6个、基础奖金100元，超额10%及以上目标奖金增加10%。双方均达标才评选PK胜利奖：先比人均新签，再比人均新签金额，最后比人均月GMV；三项均相同则持平待裁定。</p>
    </template>
  </div>
</template>
<script setup>
import { computed } from 'vue'
import { formatMoney } from '@/utils/money'
const props = defineProps({ data: { type: Object, required: true } })
const groups = computed(() => [{ key: 'qualified', label: props.data.data_complete ? '已达门槛 · 按系数排名' : '已达GMV门槛 · 排名待核对', rows: props.data.qualified || [] }, { key: 'unqualified', label: '未达GMV门槛 · 冲刺进度', rows: props.data.unqualified || [] }, ...(props.data.pending?.length ? [{ key: 'pending', label: 'GMV数据待核对', rows: props.data.pending }] : [])])
const number = (value, digits = 2) => formatMoney(value, digits)
</script>
<style scoped>
.award-overview{display:grid;gap:20px}.award-summary{display:flex;align-items:center;gap:32px;padding:24px;background:var(--card-bg);border:1px solid var(--border-color);border-radius:var(--card-radius)}.award-summary span{display:block;color:var(--text-secondary)}.award-summary strong{font-size:28px;color:var(--color-primary-text)}.award-summary p{max-width:480px;line-height:1.8;margin-left:auto}.award-overview small{font-size:13px;font-weight:400}.award-overview h3>span{font-size:13px;color:var(--text-secondary);margin-left:8px}.award-people{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.award-person,.pk-team{padding:20px;border:1px solid var(--border-color);border-radius:var(--card-radius);background:var(--card-bg)}.award-person header,.pk-team header{display:flex;justify-content:space-between;align-items:center}.award-person h4{display:flex;justify-content:space-between;gap:16px;font-size:18px;margin:16px 0}.award-person h4 b{color:var(--color-primary-text);font-variant-numeric:tabular-nums}.award-person p,.award-note{font-size:13px;line-height:1.7;color:var(--text-secondary)}.award-person footer,.pk-team footer{border-top:1px solid var(--border-color);padding-top:12px;font-size:13px;line-height:1.8}.award-top,.pk-leading{border:2px solid var(--color-primary);background:var(--color-primary-light)}.pk-heading{text-align:center}.pk-heading h3{font-size:26px;margin:0}.pk-heading p{color:var(--text-secondary)}.pk-arena{display:grid;grid-template-columns:1fr 1fr;gap:40px;position:relative}.pk-vs{position:absolute;top:110px;left:50%;transform:translateX(-50%);padding:8px;font-size:26px;font-weight:900;color:var(--color-primary-text);background:var(--card-bg)}.pk-captain{font-size:18px;font-weight:700}.pk-count{font-size:48px;font-weight:800;font-variant-numeric:tabular-nums}.pk-count small{color:var(--text-secondary)}.pk-team dl{display:grid;gap:12px;font-size:13px}.pk-team dl>div{display:flex;justify-content:space-between;gap:12px}.pk-team dd{margin:0;font-weight:700}.pk-roster{display:grid;gap:12px;margin:24px 0}.pk-roster>div{display:flex;justify-content:space-between;gap:12px}.pk-roster b{white-space:nowrap}@media(max-width:800px){.award-people,.pk-arena{grid-template-columns:1fr}.award-summary{flex-wrap:wrap}.award-summary p{margin:0}.pk-vs{position:static;grid-row:2;justify-self:center;transform:none}.pk-arena{gap:12px}.award-person h4{flex-wrap:wrap}}
</style>
