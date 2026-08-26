<template>
  <div class="holiday-card lg-card is-static">
    <div class="card-header">
      <h3 class="card-title">节假日日历</h3>
      <span class="card-subtitle">客户国家放假早知道</span>
    </div>

    <!-- 今天有国家放假：置顶横幅 -->
    <div v-if="data.todayHolidays.length > 0" class="today-banner">
      <span class="today-dot" aria-hidden="true" />
      <span class="today-text">
        今天
        <template v-for="(h, i) in data.todayHolidays" :key="`${h.code}-${h.name}`">
          <span v-if="i > 0">、</span><strong>{{ h.flag }} {{ h.country }}·{{ h.name }}</strong>
        </template>
        放假
      </span>
    </div>

    <ul class="holiday-list">
      <li
        v-for="(h, index) in shown"
        :key="`${h.date}-${h.code}-${h.name}`"
        class="holiday-row"
        :class="{ 'is-soon': h.daysUntil <= 3 }"
        :style="{ '--row-index': index }"
      >
        <span class="holiday-flag" aria-hidden="true">{{ h.flag }}</span>
        <div class="holiday-main">
          <span class="holiday-name">{{ h.country }} · {{ h.name }}</span>
          <span class="holiday-date">{{ formatDay(h.date) }}</span>
        </div>
        <span class="holiday-countdown" :class="{ urgent: h.daysUntil <= 3 }">
          {{ countdownText(h.daysUntil) }}
        </span>
      </li>
    </ul>

    <p class="card-footer-hint">假期前后客户回复与港口作业可能变慢，提前安排催办</p>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { beijingCalendarDate } from '@/utils/datetime'

const props = defineProps({
  data: { type: Object, required: true }, // reactive 化的 useDashboardData 返回
})

// 未来 60 天里取前 7 条（今天放假的已在横幅呈现，列表从明天起）
const shown = computed(() =>
  (props.data.upcomingHolidays || []).filter(h => h.daysUntil > 0).slice(0, 7)
)

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六']

function formatDay(iso) {
  const d = beijingCalendarDate(iso)
  return `${d.getMonth() + 1}月${d.getDate()}日 周${WEEKDAYS[d.getDay()]}`
}

function countdownText(daysUntil) {
  if (daysUntil <= 0) return '今天'
  if (daysUntil === 1) return '明天'
  if (daysUntil === 2) return '后天'
  return `${daysUntil} 天后`
}
</script>

<style scoped>
.holiday-card {
  padding: 18px 20px 14px;
}

.card-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 12px;
}
.card-title {
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
}
.card-subtitle {
  font-size: 11px;
  color: var(--text-muted-blue);
}

/* 今日放假横幅 */
.today-banner {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 12px;
  margin-bottom: 10px;
  border-radius: 8px;
  background: var(--color-warning-bg);
  border: 1px solid var(--color-gold);
  font-size: 12px;
  line-height: 1.5;
  color: var(--color-warning-text);
}
.today-banner strong {
  font-weight: 700;
}
.today-dot {
  width: 7px;
  height: 7px;
  margin-top: 5px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--color-primary);
  animation: dotPulse 1.8s ease-in-out infinite;
}
@keyframes dotPulse {
  0%, 100% { transform: scale(1); opacity: 1; }
  50%      { transform: scale(1.5); opacity: 0.55; }
}

.holiday-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}

.holiday-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 4px;
  border-bottom: 1px dashed var(--border-color);
  animation: rowIn 240ms var(--ease-out-strong) both;
  animation-delay: calc(var(--row-index) * 40ms);
}
.holiday-row:last-child {
  border-bottom: none;
}

.holiday-flag {
  font-size: 18px;
  flex-shrink: 0;
}

.holiday-main {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  flex: 1;
}
.holiday-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.holiday-date {
  font-size: 11px;
  color: var(--text-muted-blue);
}

.holiday-countdown {
  flex-shrink: 0;
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  background: var(--color-info-bg);
}
.holiday-countdown.urgent {
  color: var(--color-gold-muted);
  background: var(--color-gold-soft);
  border: 1px solid var(--color-gold);
}

.card-footer-hint {
  margin: 10px 0 0;
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.5;
}

@keyframes rowIn {
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: translateY(0); }
}

@media (prefers-reduced-motion: reduce) {
  .holiday-row {
    animation: rowFade 180ms ease both;
  }
  .today-dot {
    animation: none;
  }
  @keyframes rowFade {
    from { opacity: 0; }
    to   { opacity: 1; }
  }
}
</style>
