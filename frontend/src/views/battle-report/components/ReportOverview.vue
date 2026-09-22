<template>
  <div>
    <el-alert v-if="data.issue_count" type="warning" :closable="false" show-icon title="部分数据待核对：异常订单暂不计入，受影响范围不计算完成率和排名。请在可查看的订单明细中核对。" />
    <div class="battle-metrics">
      <article class="lg-card is-static"><span>当前范围 · 累计 GMV / USD</span><strong>{{ money(data.summary.gmv) }}</strong><p>{{ data.summary.filled === data.summary.member_count ? '周期目标' : '已填目标' }} ${{ money(data.summary.target) }} · 已填 {{ data.summary.filled }}/{{ data.summary.member_count }}</p></article>
      <article class="lg-card is-static"><span>目标完成率</span><strong>{{ rate(data.summary.progress_percent) }}</strong><p>时间进度 {{ data.time_progress }}% · 均匀节奏参考</p></article>
      <article class="lg-card is-static"><span>累计订单数</span><strong>{{ data.summary.order_count }} <small>单</small></strong><p>平均订单金额 ${{ money(data.summary.average_order) }}</p></article>
    </div>
    <div class="battle-section-title"><h3>业务组进度</h3><span>组目标由个人目标自动汇总</span></div>
    <div class="battle-teams">
      <article v-for="team in data.teams" :key="team.team" class="lg-card is-static">
        <el-button link type="primary" @click="$emit('team', team.team)"><el-icon><ArrowRight /></el-icon>{{ team.team }}</el-button>
        <strong>${{ money(team.gmv) }}</strong><p>目标 ${{ money(team.target) }}</p>
        <el-progress :percentage="Math.min(team.progress_percent || 0, 100)" :show-text="false" />
        <div class="battle-section-title"><b>{{ rate(team.progress_percent) }}</b><span>{{ team.order_count }} 单 · 已填 {{ team.filled }}/{{ team.member_count }}</span></div>
      </article>
    </div>
    <section class="table-card battle-panel">
      <div class="battle-section-title"><h3>个人战报</h3><el-select v-model="sort" aria-label="个人排名排序"><el-option label="按累计 GMV" value="gmv" /><el-option label="按完成率" value="rate" /></el-select></div>
      <el-table :data="ranked" class="list-table" border>
        <el-table-column prop="rank" label="排名" min-width="75" max-width="100" />
        <el-table-column label="业务员" min-width="120" max-width="160"><template #default="{ row }"><el-button link type="primary" :disabled="!row.can_view_orders" @click="$emit('review', { memberId: row.member_id })"><el-icon><ArrowRight /></el-icon>{{ row.user_name }}</el-button></template></el-table-column>
        <el-table-column prop="team" label="业务组" min-width="120" max-width="180" show-overflow-tooltip />
        <el-table-column label="目标 / USD" min-width="140" max-width="180"><template #default="{ row }">{{ row.target_usd == null ? '待填报' : money(row.target_usd) }}</template></el-table-column>
        <el-table-column label="当前 GMV / USD" min-width="160" max-width="200"><template #default="{ row }">{{ money(row.gmv) }}{{ row.data_complete ? '' : '（待核对）' }}</template></el-table-column>
        <el-table-column label="完成进度" min-width="150" max-width="180"><template #default="{ row }"><span>{{ rate(row.progress_percent) }}</span><el-progress :percentage="Math.min(row.progress_percent || 0, 100)" :show-text="false" /></template></el-table-column>
        <el-table-column label="距目标 / USD" min-width="150" max-width="180"><template #default="{ row }">{{ Number(row.excess) > 0 ? `超额 ${money(row.excess)}` : money(row.gap) }}</template></el-table-column>
        <el-table-column prop="order_count" label="订单数" min-width="95" max-width="125" />
      </el-table>
    </section>
    <section class="battle-panel table-card">
      <div class="battle-section-title"><h3>每日 GMV</h3><span>USD · 点击日期查看有权限的订单</span></div>
      <div class="battle-chart" role="group" aria-label="每日GMV柱图，横轴为日期，柱高为美元金额">
        <button v-for="day in data.daily" :key="day.date" type="button" :disabled="day.state === 'future'" :aria-label="`${day.date} ${money(day.gmv)}美元 ${day.order_count}单`" @click="$emit('review', { day: day.date })">
          <span>{{ day.state === 'future' ? '未到' : money(day.gmv) }}</span><div class="battle-chart-track"><i :style="{ height: `${day.state === 'future' ? 0 : Math.max(1, Number(day.gmv) / peak * 100)}%` }" /></div><span>{{ day.date.slice(5) }}</span>
        </button>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ArrowRight } from '@element-plus/icons-vue'
import { money, rankPeople, rate } from '../helpers'
const props = defineProps({ data: { type: Object, required: true } })
defineEmits(['team', 'review'])
const sort = ref('gmv')
const ranked = computed(() => rankPeople(props.data.people, sort.value))
const peak = computed(() => Math.max(1, ...props.data.daily.map(d => Number(d.gmv))))
</script>
