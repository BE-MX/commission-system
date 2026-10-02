<template>
  <component
    :is="interactive ? 'button' : 'div'"
    :type="interactive ? 'button' : undefined"
    class="overview-metric lg-card is-static"
    :class="[`overview-metric--${tone}`, { 'is-selected': interactive && selected }]"
    :aria-pressed="interactive ? selected : undefined"
  >
    <el-icon class="overview-metric__icon" aria-hidden="true"><component :is="icon" /></el-icon>
    <el-icon v-if="interactive && selected" class="overview-metric__selected" aria-hidden="true"><Check /></el-icon>
    <span class="overview-metric__label">{{ label }}</span>
    <strong class="overview-metric__value">{{ value }}</strong>
    <small v-if="hint" class="overview-metric__hint">{{ hint }}</small>
    <el-icon class="overview-metric__watermark" aria-hidden="true"><component :is="icon" /></el-icon>
  </component>
</template>

<script setup>
import { Check } from '@element-plus/icons-vue'

defineProps({
  label: { type: String, required: true },
  value: { type: [Number, String], default: '—' },
  icon: { type: [Object, Function], required: true },
  tone: { type: String, default: 'neutral', validator: value => ['gold', 'success', 'info', 'warning', 'violet', 'neutral'].includes(value) },
  hint: { type: String, default: '' },
  interactive: { type: Boolean, default: false },
  selected: { type: Boolean, default: false },
})
</script>

<style scoped>
.overview-metric {
  --metric-ink: var(--tag-neutral-text);
  --metric-bg: var(--tag-neutral-bg);
  position: relative;
  isolation: isolate;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 9px;
  min-width: 0;
  min-height: 142px;
  padding: 15px 18px;
  font: inherit;
  text-align: left;
  color: var(--text-primary);
  background: linear-gradient(145deg, var(--dash-glass-bg-strong), var(--metric-bg));
  transition: none;
}
.overview-metric--gold { --metric-ink: var(--tag-gold-text); --metric-bg: var(--tag-gold-bg); }
.overview-metric--success { --metric-ink: var(--tag-success-text); --metric-bg: var(--tag-success-bg); }
.overview-metric--info { --metric-ink: var(--tag-info-text); --metric-bg: var(--tag-info-bg); }
.overview-metric--warning { --metric-ink: var(--tag-warning-text); --metric-bg: var(--tag-warning-bg); }
.overview-metric--violet { --metric-ink: var(--metric-violet-ink); --metric-bg: var(--metric-violet-bg); }
.overview-metric__icon {
  z-index: 1;
  flex: 0 0 34px;
  width: 34px;
  height: 34px;
  border-radius: 10px;
  color: var(--metric-ink);
  background: var(--metric-bg);
  font-size: 20px;
}
.overview-metric__label,
.overview-metric__value,
.overview-metric__hint { position: relative; z-index: 1; max-width: 100%; overflow-wrap: anywhere; }
.overview-metric__label { font-size: 13px; color: var(--text-secondary); }
.overview-metric__value {
  font-family: var(--font-display);
  font-size: clamp(22px, 1.8vw, 26px);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  line-height: 1.1;
}
.overview-metric__hint { font-size: 12px; line-height: 1.6; color: var(--text-secondary); }
.overview-metric__watermark {
  position: absolute;
  z-index: 0;
  right: -12px;
  bottom: -18px;
  width: 112px;
  height: 112px;
  font-size: 112px;
  color: var(--metric-ink);
  opacity: 0.09;
  transform: rotate(-12deg);
  pointer-events: none;
}
.overview-metric__selected { position: absolute; z-index: 1; top: 16px; right: 16px; color: var(--metric-ink); }
button.overview-metric { cursor: pointer; }
.overview-metric.is-selected { border-color: var(--metric-ink); box-shadow: inset 0 0 0 1px var(--metric-ink), var(--dash-glass-shadow); }
button.overview-metric:focus-visible { outline: 2px solid var(--text-primary); outline-offset: 3px; }
/* Frequent filtering stays still, including keyboard and reduced-motion use. */
.overview-metric:hover { transform: none; }
@media (hover: hover) and (pointer: fine) {
  button.overview-metric:hover { border-color: var(--metric-ink); }
}
</style>
