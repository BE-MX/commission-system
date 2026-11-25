<!--
  产品风向标大类 AI 分析卡片：
  - 无结果时收为单行紧凑行动条；加载中以骨架屏预占高度避免下方表格跳动
  - 已有结果可折叠，刷新按钮降级为次操作并在 5 分钟冷却期内显示倒计时禁点
-->
<template>
  <section class="radar-card insight" :class="{ 'is-compact': !insight.data && !insight.loading && !insight.error }" :aria-busy="insight.loading">
    <div class="insight-head">
      <div class="insight-title-wrap">
        <button
          v-if="insight.data"
          type="button"
          class="insight-toggle"
          :aria-expanded="insight.expanded"
          @click="insight.expanded = !insight.expanded"
        >
          <el-icon class="toggle-chevron" :class="{ 'is-open': insight.expanded }"><ArrowRight /></el-icon>
          <h3>{{ gradeLabel }} · AI 分析</h3>
        </button>
        <h3 v-else>{{ gradeLabel }} · AI 分析</h3>

        <div v-if="insight.data" class="insight-tags">
          <span class="meta-pill">{{ timeText }}</span>
          <span v-if="insight.data.source !== 'ai'" class="meta-pill is-warn">规则摘要</span>
          <span v-if="stale" class="meta-pill is-warn">销量已变，可刷新</span>
          <span v-if="!insight.data.comparable" class="meta-pill">含估算参考</span>
        </div>
        <p v-else class="insight-desc">汇总近 {{ windowDays }} 天热销结构、涨跌规律与趋势（全公司口径）</p>
      </div>

      <div class="insight-actions">
        <span v-if="insight.data && inCooldown" class="cooldown-hint">{{ cooldownText }}</span>
        <GlassButton
          :variant="buttonVariant"
          :left-icon="insight.data ? 'Refresh' : 'MagicStick'"
          :loading="insight.loading"
          :disabled="disabled || (!!insight.data && inCooldown)"
          @click="$emit('explain')"
        >
          {{ insight.data ? '重新分析' : '生成 AI 分析' }}
        </GlassButton>
      </div>
    </div>

    <div class="collapse-shell" :class="{ 'is-open': !!insight.error || !!insight.data?.refresh_failed }">
      <div class="collapse-inner">
        <el-alert v-if="insight.error" type="error" :title="insight.error" :closable="false" show-icon class="insight-alert" />
        <el-alert v-else-if="insight.data?.refresh_failed" type="warning" title="本次重新分析未成功，已保留上次结果" :closable="false" show-icon class="insight-alert" />
      </div>
    </div>

    <div class="collapse-shell" :class="{ 'is-open': insight.loading || (!!insight.data && insight.expanded) }">
      <div class="collapse-inner">
        <div v-if="insight.loading" class="insight-skeleton" role="status">
          <span class="sk-bar sk-w-40" />
          <span class="sk-bar" />
          <span class="sk-bar sk-w-80" />
          <span class="sk-bar sk-w-60" />
          <p class="insight-loading-tip">正在基于本页证据生成分析，通常需要 10~30 秒…</p>
        </div>
        <!-- v-html 内容已在上层经 DOMPurify 清洗 -->
        <Transition v-else-if="insight.data" name="content-fade" mode="out-in">
          <div :key="contentKey" class="insight-body" v-html="html" />
        </Transition>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ArrowRight } from '@element-plus/icons-vue'
import { computed } from 'vue'

import { currentBeijingDate, formatBeijingDate, formatBeijingShortDateTime, formatBeijingTime } from '@/utils/datetime'

const props = defineProps({
  insight: { type: Object, required: true },
  gradeLabel: { type: String, required: true },
  windowDays: { type: Number, required: true },
  html: { type: String, default: '' },
  contentKey: { type: String, default: '' },
  stale: { type: Boolean, default: false },
  inCooldown: { type: Boolean, default: false },
  cooldownSeconds: { type: Number, default: 0 },
  disabled: { type: Boolean, default: false },
})
defineEmits(['explain'])

const timeText = computed(() => {
  const raw = props.insight.data?.created_at
  if (!raw) return ''
  return formatBeijingDate(raw) === currentBeijingDate()
    ? `今天 ${formatBeijingTime(raw, { seconds: false })}`
    : formatBeijingShortDateTime(raw)
})
const cooldownText = computed(() => `${Math.max(1, Math.ceil(props.cooldownSeconds / 60))} 分钟后可刷新`)
const buttonVariant = computed(() => {
  if (!props.insight.data) return 'primary'
  return props.stale && !props.inCooldown ? 'secondary' : 'ghost'
})
</script>

<style scoped>
.radar-card {
  padding: 14px 16px;
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
}
.insight.is-compact { padding: 10px 16px; }
.insight-head { display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; justify-content: space-between; }
.insight-title-wrap { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 10px; min-width: 0; }
.insight-head h3 { margin: 0; font-family: var(--font-display); font-size: 14px; font-weight: 700; }
.insight-toggle { display: inline-flex; align-items: center; gap: 6px; padding: 2px 4px 2px 0; border: 0; background: transparent; color: inherit; cursor: pointer; }
.insight-toggle:focus-visible { outline: 2px solid var(--color-primary); border-radius: 4px; }
.toggle-chevron { font-size: 12px; color: var(--text-secondary); transition: transform var(--motion-fast) var(--ease-out-strong); }
.toggle-chevron.is-open { transform: rotate(90deg); }
.insight-tags { display: inline-flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.meta-pill { padding: 2px 7px; border-radius: 6px; background: var(--tag-neutral-bg); color: var(--tag-neutral-text); font-size: 11px; font-variant-numeric: tabular-nums; }
.meta-pill.is-warn { background: var(--tag-warning-bg); color: var(--tag-warning-text); }
.insight-desc { margin: 0; color: var(--text-secondary); font-size: 12px; }
.insight-actions { display: inline-flex; align-items: center; gap: 8px; }
.cooldown-hint { color: var(--text-muted); font-size: 12px; font-variant-numeric: tabular-nums; }
.insight-alert { margin-top: 8px; }

.collapse-shell { display: grid; grid-template-rows: 0fr; opacity: 0; transition: grid-template-rows var(--motion-fast) var(--ease-out-strong), opacity var(--motion-fast) var(--ease-out-strong); }
.collapse-shell.is-open { grid-template-rows: 1fr; opacity: 1; transition: grid-template-rows var(--motion-base) var(--ease-out-strong), opacity var(--motion-base) var(--ease-out-strong); }
.collapse-inner { overflow: hidden; min-height: 0; }

.insight-skeleton { display: flex; flex-direction: column; gap: 10px; padding-top: 12px; }
.insight-loading-tip { margin: 2px 0 0; color: var(--text-secondary); font-size: 12px; }
.sk-bar { display: block; height: 14px; width: 100%; border-radius: 6px; background: var(--border-color); opacity: 0.5; animation: insight-pulse 1.4s ease-in-out infinite; }
.sk-w-40 { width: 40%; }
.sk-w-60 { width: 60%; }
.sk-w-80 { width: 80%; }
@keyframes insight-pulse { 0%, 100% { opacity: 0.35; } 50% { opacity: 0.7; } }

.insight-body { margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--border-color); font-size: 13px; line-height: 1.75; }
.insight-body :deep(p) { margin: 4px 0; }
.insight-body :deep(ul), .insight-body :deep(ol) { margin: 4px 0; padding-left: 20px; }

.content-fade-enter-active, .content-fade-leave-active { transition: opacity var(--motion-fast) var(--ease-out-strong); }
.content-fade-enter-from, .content-fade-leave-to { opacity: 0; }

@media (prefers-reduced-motion: reduce) {
  .sk-bar { animation: none; opacity: 0.45; }
}
</style>
