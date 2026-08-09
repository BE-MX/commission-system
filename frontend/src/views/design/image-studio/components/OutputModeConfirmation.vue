<template>
  <section class="output-mode-confirmation" aria-label="选择生成方式">
    <p class="confirmation-title">请选择生成方式</p>
    <p v-if="isAngle" class="confirmation-labels">标准角度：{{ labelsText }}</p>
    <p v-else class="confirmation-labels">版本：{{ labelsText }}</p>

    <p v-if="resolved" class="resolved-state" role="status">
      已选择：{{ selectedLabel }}
    </p>
    <div v-else class="mode-options">
      <button
        type="button"
        class="mode-option"
        :disabled="submitting"
        @click="emit('choose', 'composite')"
      >
        <strong>{{ compositeLabel }}</strong>
        <span>{{ compositeDescription }} · 消耗 1 次</span>
      </button>
      <button
        type="button"
        class="mode-option"
        :disabled="submitting"
        @click="emit('choose', 'separate')"
      >
        <strong>{{ separateLabel }}</strong>
        <span>{{ separateDescription }} · 消耗 {{ interaction.count }} 次</span>
      </button>
    </div>
    <p v-if="submitting" class="submitting-state" role="status">正在确认，请稍候…</p>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  interaction: { type: Object, required: true },
  submitting: { type: Boolean, default: false },
})
const emit = defineEmits(['choose'])

const resolved = computed(() => props.interaction.status === 'resolved')
const isAngle = computed(() => props.interaction.item_kind === 'angle')
const labelsText = computed(() => (props.interaction.labels || []).join('、'))
const compositeLabel = computed(() => (
  isAngle.value ? `一张${props.interaction.count}视图拼版` : '同图对比版'
))
const compositeDescription = computed(() => (
  isAngle.value
    ? `${props.interaction.count} 个角度放在同一张图中`
    : `${props.interaction.count} 个版本放在同一张图中`
))
const separateLabel = computed(() => (
  isAngle.value
    ? `分别生成 ${props.interaction.count} 张`
    : `分别生成 ${props.interaction.count} 个版本`
))
const separateDescription = computed(() => (
  isAngle.value ? '每个角度独立生成' : '每个版本独立生成'
))
const selectedLabel = computed(() => (
  props.interaction.selected_mode === 'separate'
    ? separateLabel.value
    : compositeLabel.value
))
</script>

<style scoped>
.output-mode-confirmation {
  max-width: 620px; margin: -4px auto 18px; padding: 16px;
  border: 1px solid var(--border-color); border-radius: 14px;
  background: rgba(255, 255, 255, 0.78); box-shadow: 0 8px 24px rgba(146, 103, 24, 0.1);
  animation: confirmation-enter 180ms cubic-bezier(0.23, 1, 0.32, 1) both;
}
.confirmation-title { margin: 0; color: var(--text-primary); font-size: 14px; font-weight: 700; }
.confirmation-labels { margin: 5px 0 12px; color: var(--text-secondary); font-size: 12px; line-height: 1.6; }
.mode-options { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.mode-option {
  min-height: 44px; padding: 11px 12px; border: 1px solid var(--border-color); border-radius: 11px;
  background: var(--card-bg); color: var(--text-primary); cursor: pointer; text-align: left;
  transition: border-color 160ms cubic-bezier(0.23, 1, 0.32, 1),
    background-color 160ms cubic-bezier(0.23, 1, 0.32, 1),
    transform 160ms cubic-bezier(0.23, 1, 0.32, 1);
}
.mode-option strong, .mode-option span { display: block; }
.mode-option strong { font-size: 13px; }
.mode-option span { margin-top: 4px; color: var(--text-muted); font-size: 11px; line-height: 1.45; }
.mode-option:active { transform: scale(0.98); }
.mode-option:disabled { cursor: wait; opacity: 0.58; }
.resolved-state {
  margin: 0; padding: 11px 12px; border-radius: 10px;
  background: var(--color-primary-light); color: var(--color-gold-muted); font-size: 13px; font-weight: 600;
}
.submitting-state { margin: 9px 0 0; color: var(--text-muted); font-size: 11px; }

@keyframes confirmation-enter {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}
@media (hover: hover) and (pointer: fine) {
  .mode-option:not(:disabled):hover {
    border-color: var(--color-primary); background: var(--color-primary-light); transform: translateY(-1px);
  }
}
@media (max-width: 640px) {
  .mode-options { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) {
  .output-mode-confirmation { animation: none; }
  .mode-option { transition: none; }
  .mode-option:active, .mode-option:not(:disabled):hover { transform: none; }
}
</style>
