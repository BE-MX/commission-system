<template>
  <div v-if="missing?.applicable" class="stats-missing" :class="{ 'stats-missing--ok': !missing.users?.length }">
    <el-icon v-if="missing.users?.length"><Warning /></el-icon>
    <el-icon v-else><CircleCheck /></el-icon>
    <template v-if="missing.users?.length">
      <span><strong>今日未提交 {{ missing.users.length }} 人</strong></span>
      <span v-for="row in missing.users" :key="row.user.id" class="stats-missing__who">
        <span class="stats-avatar">{{ row.user.real_name.slice(-1) }}</span>{{ row.user.real_name }}
        <small>{{ row.missing_streak > 1 ? `连续 ${row.missing_streak} 个工作日` : '今天' }} · 上次 {{ shortDate(row.last_submission_date) }}</small>
      </span>
      <span class="stats-spacer" /><span>周日和配置的非工作日不计</span>
    </template>
    <span v-else>{{ single ? '今天已提交跟进记录' : '今天全员已提交跟进记录' }}</span>
  </div>
</template>
<script setup>
import { CircleCheck, Warning } from '@element-plus/icons-vue'
import { shortDate } from './statsModel'
defineProps({ missing: Object, single: Boolean })
</script>
