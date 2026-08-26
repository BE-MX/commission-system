<template>
  <div class="logistics-card lg-card is-static">
    <div class="card-header">
      <h3 class="card-title">物流进度</h3>
      <router-link to="/tracking" class="card-link">
        查看全部 <el-icon><ArrowRight /></el-icon>
      </router-link>
    </div>

    <ul v-if="shipments.length > 0" class="shipment-list">
      <li
        v-for="(s, index) in shipments"
        :key="s.waybill_no"
        class="shipment-row"
        :style="{ '--row-index': index }"
        @click="$router.push('/tracking')"
      >
        <div class="shipment-top">
          <span class="carrier">{{ s.carrier_name || s.carrier }}</span>
          <span class="waybill">{{ s.waybill_no }}</span>
          <span class="destination">{{ countryFlag(s.receiver_country) }} {{ s.receiver_country || '未知目的地' }}</span>
        </div>

        <!-- 进度步条：揽收 → 运输 → 派送 → 签收 -->
        <div class="step-track" :class="`is-${stepInfo(s).tone}`">
          <div class="step-fill" :style="{ transform: `scaleX(${stepInfo(s).percent / 100})` }" />
          <div
            v-for="(label, i) in STEP_LABELS"
            :key="label"
            class="step-node"
            :class="{ done: i <= stepInfo(s).step }"
            :style="{ left: `${(i / (STEP_LABELS.length - 1)) * 100}%` }"
          >
            <span class="step-dot" />
            <span class="step-label">{{ label }}</span>
          </div>
        </div>

        <div class="shipment-meta">
          <span class="meta-status" :class="`is-${stepInfo(s).tone}`">{{ statusText(s) }}</span>
          <span v-if="s.current_location" class="meta-item">{{ s.current_location }}</span>
          <span v-if="s.last_event_time" class="meta-item">{{ relativeTime(s.last_event_time) }}</span>
          <span v-if="etaText(s)" class="meta-eta">{{ etaText(s) }}</span>
        </div>
      </li>
    </ul>

    <div v-else class="empty-state">
      <el-icon class="empty-icon"><Van /></el-icon>
      <span>当前没有在途运单，一路顺风</span>
    </div>
  </div>
</template>

<script setup>
import { beijingCalendarDaysUntil, formatBeijingDate, parseApiDateTime } from '@/utils/datetime'

/**
 * 物流进度卡 — 在途运单的阶段化进度 + 异常高亮 + ETA 倒计时。
 * 状态口径与后端 tracking/status.py 统一状态码一致（current_status 存的就是统一码）。
 */
import { computed } from 'vue'
import { ArrowRight, Van } from '@element-plus/icons-vue'

const props = defineProps({
  data: { type: Object, required: true },
})

const shipments = computed(() => (props.data.recentShipments || []).slice(0, 5))

const STEP_LABELS = ['揽收', '运输', '派送', '签收']

// 统一状态码 → 步条进度/色调
//   step: 已到达的节点下标（-1=未开始）  percent: 填充宽度  tone: 配色语义
const STATUS_STEP = {
  pending:          { step: -1, percent: 2,   tone: 'muted' },
  picked_up:        { step: 0,  percent: 12,  tone: 'info' },
  in_transit:       { step: 1,  percent: 45,  tone: 'info' },
  customs_hold:     { step: 1,  percent: 55,  tone: 'warning' },
  out_for_delivery: { step: 2,  percent: 78,  tone: 'info' },
  delivered:        { step: 3,  percent: 100, tone: 'success' },
  exception:        { step: 1,  percent: 45,  tone: 'danger' },
  returned:         { step: 1,  percent: 30,  tone: 'danger' },
}

const STATUS_TEXT = {
  pending: '待查询', picked_up: '已揽收', in_transit: '运输中',
  customs_hold: '清关中', out_for_delivery: '派送中', delivered: '已签收',
  exception: '异常', returned: '已退回',
}

function stepInfo(s) {
  return STATUS_STEP[s.current_status] || { step: 1, percent: 45, tone: 'info' }
}

function statusText(s) {
  return STATUS_TEXT[s.current_status] || s.current_status_text || s.current_status || '未知'
}

// 收件国家是自由文本（美国/USA/United States 都可能），做常见别名映射
const COUNTRY_FLAGS = [
  [/美国|美國|usa|united states|u\.s\./i, '🇺🇸'],
  [/英国|英國|uk|united kingdom|britain/i, '🇬🇧'],
  [/德国|德國|germany|deutschland/i, '🇩🇪'],
  [/法国|法國|france/i, '🇫🇷'],
  [/意大利|italy|italia/i, '🇮🇹'],
  [/西班牙|spain|españa/i, '🇪🇸'],
  [/荷兰|荷蘭|netherlands|holland/i, '🇳🇱'],
  [/日本|japan/i, '🇯🇵'],
  [/韩国|韓國|korea/i, '🇰🇷'],
  [/澳大利亚|澳洲|australia/i, '🇦🇺'],
  [/加拿大|canada/i, '🇨🇦'],
  [/墨西哥|mexico/i, '🇲🇽'],
  [/巴西|brazil/i, '🇧🇷'],
  [/阿联酋|阿聯酋|uae|emirates|dubai/i, '🇦🇪'],
  [/沙特|saudi/i, '🇸🇦'],
  [/中国|中國|china/i, '🇨🇳'],
]

function countryFlag(country) {
  if (!country) return '🌐'
  const hit = COUNTRY_FLAGS.find(([pattern]) => pattern.test(country))
  return hit ? hit[1] : '🌐'
}

function relativeTime(dateLike) {
  const t = parseApiDateTime(dateLike)
  if (!t) return ''
  const diffMin = Math.max(0, Math.floor((Date.now() - t.getTime()) / 60000))
  if (diffMin < 60) return `${diffMin || 1} 分钟前`
  const diffHour = Math.floor(diffMin / 60)
  if (diffHour < 24) return `${diffHour} 小时前`
  const diffDay = Math.floor(diffHour / 24)
  if (diffDay < 30) return `${diffDay} 天前`
  const [, month, day] = formatBeijingDate(t).split('-')
  return `${Number(month)}月${Number(day)}日`
}

function etaText(s) {
  if (!s.estimated_delivery_date || s.current_status === 'delivered') return ''
  const days = beijingCalendarDaysUntil(s.estimated_delivery_date)
  if (days == null) return ''
  if (days < 0) return '预计送达已过，待更新'
  if (days === 0) return '预计今天送达'
  if (days === 1) return '预计明天送达'
  return `预计 ${days} 天后送达`
}
</script>

<style scoped>
.logistics-card {
  padding: 18px 20px 14px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.card-title {
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
}
.card-link {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 12px;
  color: var(--color-primary);
  text-decoration: none;
  transition: color 140ms ease;
}
@media (hover: hover) and (pointer: fine) {
  .card-link:hover {
    color: var(--color-primary-hover);
  }
}

.shipment-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.shipment-row {
  padding: 10px 6px;
  border-bottom: 1px dashed var(--border-color);
  border-radius: 8px;
  cursor: pointer;
  transition: background-color 140ms ease;
  animation: rowIn 240ms var(--ease-out-strong) both;
  animation-delay: calc(var(--row-index) * 40ms);
}
.shipment-row:last-child {
  border-bottom: none;
}
@media (hover: hover) and (pointer: fine) {
  .shipment-row:hover {
    background: var(--table-row-hover);
  }
}

.shipment-top {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}
.carrier {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 700;
  color: var(--color-gold-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.waybill {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.destination {
  margin-left: auto;
  flex-shrink: 0;
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
}

/* ── 步条 ── */
.step-track {
  position: relative;
  height: 26px;
  margin: 8px 0 4px;
}
.step-track::before {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  top: 5px;
  height: 3px;
  border-radius: 2px;
  background: var(--border-color);
}
.step-fill {
  position: absolute;
  left: 0;
  top: 5px;
  width: 100%;
  height: 3px;
  border-radius: 2px;
  background: var(--color-info-text);
  transform-origin: left center;
  transition: transform 300ms var(--ease-out-strong);
}
.is-success .step-fill { background: var(--color-success); }
.is-warning .step-fill { background: var(--el-warning); }
.is-danger .step-fill  { background: var(--color-danger); }
.is-muted .step-fill   { background: var(--text-muted); }

.step-node {
  position: absolute;
  top: 0;
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
}
.step-node:first-child { transform: translateX(0); align-items: flex-start; }
.step-node:last-child  { transform: translateX(-100%); align-items: flex-end; }
.step-dot {
  width: 11px;
  height: 11px;
  border-radius: 50%;
  border: 2px solid var(--border-color);
  background: var(--card-bg);
  transition: border-color 200ms ease, background-color 200ms ease;
}
.step-node.done .step-dot {
  border-color: var(--color-info-text);
  background: var(--color-info-text);
}
.is-success .step-node.done .step-dot { border-color: var(--color-success); background: var(--color-success); }
.is-warning .step-node.done .step-dot { border-color: var(--el-warning); background: var(--el-warning); }
.is-danger .step-node.done .step-dot  { border-color: var(--color-danger); background: var(--color-danger); }
.step-label {
  font-size: 10px;
  color: var(--text-muted);
  white-space: nowrap;
}
.step-node.done .step-label {
  color: var(--text-secondary);
}

/* ── 元信息行 ── */
.shipment-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 10px;
  font-size: 11px;
  color: var(--text-muted-blue);
}
.meta-status {
  font-weight: 700;
}
.meta-status.is-info    { color: var(--color-info-text); }
.meta-status.is-success { color: var(--color-success-text); }
.meta-status.is-warning { color: var(--color-warning-text); }
.meta-status.is-danger  { color: var(--color-danger-text); }
.meta-status.is-muted   { color: var(--text-muted); }
.meta-eta {
  margin-left: auto;
  color: var(--color-gold-muted);
  font-weight: 600;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 26px 0 20px;
  color: var(--text-muted);
  font-size: 12px;
}
.empty-icon {
  font-size: 18px;
}

@keyframes rowIn {
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: translateY(0); }
}

@media (prefers-reduced-motion: reduce) {
  .shipment-row {
    animation: rowFade 180ms ease both;
  }
  .step-fill {
    transition: none;
  }
  @keyframes rowFade {
    from { opacity: 0; }
    to   { opacity: 1; }
  }
}
</style>
