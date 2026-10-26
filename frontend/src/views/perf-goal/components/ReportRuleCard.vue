<template>
  <div class="pg-card" style="margin-bottom:0">
    <div class="pg-card-title"><h2>推送规则</h2></div>
    <div class="pg-rule-line">
      <span class="pg-big">{{ cronText }}</span>
      <span class="pg-badge pg-blue"><span class="pg-dot"></span>AI 分析 · perf_report_analyst preset</span>
    </div>
    <div class="pg-countdown" v-if="schedule?.next_run_at">
      下次推送：<b>{{ formatBeijingDateTime(schedule.next_run_at) }}</b>（{{ remainText }}） · 触发后自动补发失败项 · 时区 Asia/Shanghai
    </div>
    <div class="pg-countdown" v-else>推送计划未配置或后端尚未接入。</div>
    <div class="pg-role-cards">
      <div class="pg-role-card">
        <h4><span class="pg-r-ico" style="background:var(--pg-primary)">员</span>业务员</h4>
        <p>仅接收<b>本人</b>报告：四指标完成、与时间进度差、缺口与日均冲刺量、亮点/风险订单。</p>
      </div>
      <div class="pg-role-card">
        <h4><span class="pg-r-ico" style="background:var(--pg-purple)">组</span>组长（队长）</h4>
        <p>接收<b>本人 + 本战队</b>报告：战队汇总、队内排名、掉队预警、缺口分解到人。</p>
      </div>
      <div class="pg-role-card">
        <h4><span class="pg-r-ico" style="background:var(--pg-teal)">管</span>管理层</h4>
        <p>接收<b>整体</b>报告：公司四指标、战队对比、TOP/末位、缺口预测、需关注名单。</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { formatBeijingDateTime } from '@/utils/datetime'

const props = defineProps({
  schedule: { type: Object, default: null },
})
const cronText = computed(() => {
  const cron = props.schedule?.cron
  if (!cron) return '每月 1 / 10 / 20 日 09:00 自动生成并推送'
  return cronTextMap(cron)
})
function cronTextMap(cron) {
  if (cron === '0 9 1,10,20 * *') return '每月 1 / 10 / 20 日 09:00 自动生成并推送'
  return `推送计划：${cron}`
}
const remainText = computed(() => {
  const at = props.schedule?.next_run_at
  if (!at) return ''
  const diff = new Date(at).getTime() - Date.now()
  if (diff <= 0) return '即将推送'
  const days = Math.floor(diff / 86400000)
  const hours = Math.floor((diff % 86400000) / 3600000)
  return days > 0 ? `距今 ${days} 天 ${hours} 小时` : `距今 ${hours} 小时`
})
</script>
