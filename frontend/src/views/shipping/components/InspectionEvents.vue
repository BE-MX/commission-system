<template>
  <details class="inspection-events">
    <summary>操作记录（最近 {{ events.length }} 条）</summary>
    <p v-if="!events.length">暂无操作记录，历史记录不补造。</p>
    <ol v-else><li v-for="event in events" :key="event.id"><strong>{{ event.operator_name }}</strong> · {{ actions[event.action] || event.action }}<span>{{ formatDateTime(event.created_at) }} · {{ sources[event.source] || event.source }}</span><small v-if="event.login_name">登录账号：{{ event.login_name }}</small></li></ol>
  </details>
</template>
<script setup>
import { formatBeijingDateTime as formatDateTime } from '@/utils/datetime'
defineProps({ events: { type: Array, default: () => [] } })
const actions = { scan: '扫描出库单', upload: '上传媒体', delete: '删除媒体', submit: '提交验货', end: '结束本次操作', recall: '撤回编辑' }
const sources = { mini: '小程序', web_station: '共用手机网页', pc: '方舟后台' }
</script>
<style scoped>
.inspection-events{margin-top:24px;border:1px solid var(--border-color);padding:16px;border-radius:12px}.inspection-events summary{cursor:pointer;font-weight:600;min-height:28px}.inspection-events ol{list-style:none;padding:0}.inspection-events li{padding:12px 0;border-bottom:1px solid var(--border-color)}.inspection-events span,.inspection-events small{display:block;margin-top:4px;color:var(--text-secondary)}
</style>
