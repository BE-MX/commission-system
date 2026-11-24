<template>
  <div class="express-picker" role="radiogroup" aria-label="快递渠道" :aria-describedby="captionId">
    <!-- 当前值不在选项里：不合规显示划线，合规的历史/外部文本按已选显示 -->
    <div v-if="extraValue" class="channel-row current-row">
      <span v-if="stale" class="channel-option is-stale">{{ modelValue }}</span>
      <span v-else class="channel-option is-current" :aria-label="`当前渠道：${modelValue}`">{{ modelValue }}</span>
    </div>
    <div v-if="!allowed" class="channel-groups">
      <template v-for="group in PAYMENT_CHANNEL_GROUPS" :key="group.key">
        <span class="group-name" aria-hidden="true">{{ group.short }}</span>
        <div class="channel-row" role="group" :aria-label="`${group.short}渠道`">
          <button v-for="option in group.channels" :key="option" type="button" role="radio"
            :aria-checked="modelValue === option" class="channel-option" @click="pick(option)">{{ option }}</button>
        </div>
      </template>
      <span class="group-name" aria-hidden="true">通用</span>
      <div class="channel-row" role="group" aria-label="通用渠道">
        <button type="button" role="radio" :aria-checked="modelValue === ANY_EXPRESS_CHANNEL" class="channel-option"
          @click="pick(ANY_EXPRESS_CHANNEL)">{{ ANY_EXPRESS_CHANNEL }}</button>
      </div>
    </div>
    <div v-else class="channel-row">
      <template v-for="option in allowed" :key="option">
        <span v-if="option === ANY_EXPRESS_CHANNEL" class="channel-divider" aria-hidden="true" />
        <button type="button" role="radio" :aria-checked="modelValue === option" class="channel-option"
          @click="pick(option)">{{ option }}</button>
      </template>
    </div>
    <div :id="captionId" class="channel-caption" :class="{ 'is-stale-caption': stale }">{{ caption }}</div>
    <div v-if="notice && !stale" class="channel-notice" role="status">{{ notice }}</div>
  </div>
</template>

<script>
// 模块级计数：每个实例一个稳定的说明文字 id
let pickerSeq = 0
</script>

<script setup>
import { computed } from 'vue'
import {
  ANY_EXPRESS_CHANNEL,
  EXPRESS_CHANNEL_OPTIONS,
  PAYMENT_CHANNEL_GROUPS,
  channelsForPayment,
  paymentChannelError,
  paymentGroupOf,
} from '../composables/invoiceSettlement.js'

const props = defineProps({
  modelValue: { type: String, default: '' },
  paymentMethod: { type: String, default: '' },
  notice: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue'])

const allowed = computed(() => channelsForPayment(props.paymentMethod))
// 旧订单的渠道与付款方式不符：保留原值展示，保存前须改选
const stale = computed(() => Boolean(props.modelValue && paymentChannelError(props.paymentMethod, props.modelValue)))
const extraValue = computed(() => Boolean(props.modelValue && !(allowed.value || EXPRESS_CHANNEL_OPTIONS).includes(props.modelValue)))
const captionId = `express-channel-caption-${++pickerSeq}`
const caption = computed(() => {
  if (stale.value) return `原渠道「${props.modelValue}」与付款方式不符，保存前请改选`
  const group = paymentGroupOf(props.paymentMethod)
  return group ? `按「${group.label}」显示，其他渠道需换付款方式` : '选了付款方式后只显示能用的渠道'
})

function pick(option) {
  emit('update:modelValue', option)
}
</script>

<style scoped>
.express-picker { width: 100%; }
.channel-groups { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 8px 12px; align-items: center; }
.group-name { color: var(--text-muted); font-size: 12px; text-align: right; }
.channel-row { display: flex; flex-wrap: wrap; gap: 8px; }
.channel-option {
  height: 32px; padding: 0 14px; border: 1px solid var(--border-color); border-radius: 6px;
  background: var(--card-bg); color: var(--text-secondary); font: inherit; font-size: 13px; line-height: 30px;
  cursor: pointer; transition: background-color 120ms ease, border-color 120ms ease, color 120ms ease, transform 120ms cubic-bezier(0.23, 1, 0.32, 1);
}
.channel-option:active { transform: scale(0.97); }
.channel-option:focus-visible { outline: none; box-shadow: 0 0 0 3px var(--color-primary-glow); }
@media (hover: hover) and (pointer: fine) {
  .channel-option:not([aria-checked="true"]):not(.is-stale):hover { border-color: var(--border-hover); color: var(--text-primary); }
}
.channel-option[aria-checked="true"] {
  border-color: var(--color-primary); background: var(--color-primary-light); color: var(--color-primary-text); font-weight: 600;
}
.channel-option.is-stale {
  border-color: var(--color-danger); background: var(--color-danger-bg); color: var(--color-danger-text);
  text-decoration: line-through; cursor: default;
}
.channel-option.is-stale:active { transform: none; }
.channel-option.is-current {
  border-color: var(--color-primary); background: var(--color-primary-light); color: var(--color-primary-text); font-weight: 600; cursor: default;
}
.current-row { margin-bottom: 8px; }
.channel-caption.is-stale-caption { color: var(--color-danger-text); }
.channel-divider { width: 1px; align-self: stretch; margin: 4px 2px; background: var(--border-color); }
.channel-caption { margin-top: 6px; color: var(--text-muted); font-size: 12px; line-height: 1.4; }
.channel-notice {
  display: inline-block; margin-top: 6px; padding: 4px 10px; border-radius: 6px; font-size: 12px; line-height: 1.5;
  color: var(--color-warning-text); background: var(--color-warning-bg);
}
@media (prefers-reduced-motion: reduce) {
  .channel-option:active { transform: none; }
}
@media (max-width: 600px) {
  .channel-groups { grid-template-columns: minmax(0, 1fr); gap: 4px; }
  .group-name { text-align: left; margin-top: 4px; }
}
</style>
