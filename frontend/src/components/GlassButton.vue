<template>
  <button
    :class="btnClasses"
    :disabled="disabled || loading"
    :aria-busy="loading || undefined"
    :type="nativeType"
    @click="handleClick"
  >
    <!-- Loading spinner -->
    <span v-if="loading" class="gb-icon gb-icon--left">
      <el-icon class="is-loading"><Loading /></el-icon>
    </span>

    <!-- Left icon (slot takes priority over prop) -->
    <span v-else-if="hasLeftIcon" class="gb-icon gb-icon--left">
      <slot name="left-icon">
        <el-icon><component :is="resolvedLeftIcon" /></el-icon>
      </slot>
    </span>

    <!-- Content -->
    <span class="gb-content"><slot /></span>

    <!-- Right icon (slot takes priority over prop) -->
    <span v-if="hasRightIcon" class="gb-icon gb-icon--right">
      <slot name="right-icon">
        <el-icon><component :is="rightIcon" /></el-icon>
      </slot>
    </span>
  </button>
</template>

<script setup>
import { computed, useSlots } from 'vue'
import { Loading } from '@element-plus/icons-vue'

const props = defineProps({
  variant: { type: String, default: 'secondary' },
  size:    { type: String, default: 'md' },
  radius:  { type: String, default: 'lg' },

  /** Shorthand for leftIcon (compatible with Element Plus :icon usage) */
  icon:      { type: [String, Object], default: '' },
  leftIcon:  { type: [String, Object], default: '' },
  rightIcon: { type: [String, Object], default: '' },

  /** Only effective when variant="link". Values: primary | success | danger | warning */
  linkTone: { type: String, default: '' },

  loading:     { type: Boolean, default: false },
  disabled:    { type: Boolean, default: false },
  fullWidth:   { type: Boolean, default: false },
  active:      { type: Boolean, default: false },
  nativeType:  { type: String,  default: 'button' },

  /** true | false | 'sm' | 'md' | 'lg' | 'xl' */
  shadow: { type: [Boolean, String], default: true },
})

const emit = defineEmits(['click'])
const slots = useSlots()

const resolvedLeftIcon = computed(() => props.leftIcon || props.icon)
const hasLeftIcon  = computed(() => !!slots['left-icon'] || !!resolvedLeftIcon.value)
const hasRightIcon = computed(() => !!slots['right-icon'] || !!props.rightIcon)

const btnClasses = computed(() => {
  const c = [
    'glass-button',
    `gb-variant--${props.variant}`,
    `gb-size--${props.size}`,
    `gb-radius--${props.radius}`,
  ]
  if (props.linkTone)        c.push(`gb-link-tone--${props.linkTone}`)
  if (props.fullWidth)       c.push('gb-full-width')
  if (props.disabled || props.loading) c.push('gb-disabled')
  if (props.loading && !props.disabled) c.push('gb-loading')
  if (props.active)          c.push('gb-active')

  if (props.variant !== 'link' && props.shadow !== false && !props.disabled) {
    const sv = typeof props.shadow === 'string' ? props.shadow : 'default'
    c.push(`gb-shadow--${sv}`)
  }
  return c
})

function handleClick(e) {
  if (props.disabled || props.loading) return
  emit('click', e)
}
</script>

<style scoped>
/* ===== Base ===== */
.glass-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
  transition: color 160ms ease, background-color 160ms ease, border-color 160ms ease,
    box-shadow 160ms ease, opacity 160ms ease, transform 120ms var(--ease-out-strong);
  user-select: none;
  font-family: var(--font-display);
  font-weight: 600;
  cursor: pointer;
  border: none;
  outline: none;
  white-space: nowrap;
  line-height: 1;
}

.glass-button:focus-visible {
  outline: 2px solid var(--button-primary);
  outline-offset: 3px;
}

/* ===== Sizes ===== */
.gb-size--xs { height: 28px; padding: 0 10px; font-size: 11px; gap: 4px; }
.gb-size--sm { height: 32px; padding: 0 12px; font-size: 12px; gap: 6px; }
.gb-size--md { height: 36px; padding: 0 16px; font-size: 13px; gap: 6px; }
.gb-size--lg { height: 40px; padding: 0 20px; font-size: 13px; gap: 8px; }
.gb-size--xl { height: 48px; padding: 0 24px; font-size: 14px; gap: 10px; }

/* ===== Radius ===== */
.gb-radius--none { border-radius: 0; }
.gb-radius--sm   { border-radius: 4px; }
.gb-radius--md   { border-radius: 6px; }
.gb-radius--lg   { border-radius: 12px; }
.gb-radius--xl   { border-radius: 16px; }
.gb-radius--full { border-radius: 9999px; }

/* ===== Layout modifiers ===== */
.gb-full-width { width: 100%; }

.gb-disabled {
  cursor: not-allowed;
  pointer-events: none;
}
.gb-loading { opacity: 0.7; }

/* ===== Icon & content ===== */
.gb-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.gb-icon :deep(.el-icon) {
  font-size: 1em;
}

.gb-content {
  position: relative;
  z-index: 2;
}

/* ===== Shadows ===== */
.gb-shadow--default { box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.gb-shadow--sm      { box-shadow: 0 1px 3px rgba(0,0,0,0.04); }
.gb-shadow--md      { box-shadow: 0 4px 12px rgba(0,0,0,0.08); }
.gb-shadow--lg      { box-shadow: 0 8px 24px rgba(0,0,0,0.1); }
.gb-shadow--xl      { box-shadow: 0 12px 32px rgba(0,0,0,0.12); }

/* ===== Variants ===== */
.glass-button {
  --action-color: var(--button-primary);
  --action-hover: var(--button-primary-hover);
  --action-active: var(--button-primary-active);
  --action-soft: var(--button-primary-soft);
  --action-ink: var(--button-surface);
  --action-link: var(--button-primary-text);
  --action-link-hover: var(--button-primary-text-hover);
  --action-link-active: var(--button-primary-text-active);
  border: 1px solid transparent;
}
.gb-variant--primary, .gb-variant--info {
  --action-ink: var(--button-primary-ink);
}
.gb-variant--primary {
  background: var(--action-color);
  border-color: var(--action-color);
  color: var(--action-ink);
}
.gb-variant--info {
  background: var(--action-color);
  border-color: var(--action-color);
  color: var(--action-ink);
}
.gb-variant--danger {
  --action-color: var(--button-danger);
  --action-hover: var(--button-danger-hover);
  --action-active: var(--button-danger-active);
  --action-soft: var(--button-danger-soft);
  background: var(--action-color);
  border-color: var(--action-color);
  color: var(--action-ink);
}
.gb-variant--success {
  --action-color: var(--button-success);
  --action-hover: var(--button-success-hover);
  --action-active: var(--button-success-active);
  --action-soft: var(--button-success-soft);
  background: var(--action-color);
  border-color: var(--action-color);
  color: var(--action-ink);
}
.gb-variant--warning {
  --action-color: var(--button-warning);
  --action-hover: var(--button-warning-hover);
  --action-active: var(--button-warning-active);
  --action-soft: var(--button-warning-soft);
  --action-ink: var(--button-surface);
  background: var(--action-color);
  border-color: var(--action-color);
  color: var(--action-ink);
}
.gb-variant--secondary, .gb-variant--outline, .gb-variant--white {
  background: var(--button-surface);
  border-color: var(--button-border);
  color: var(--button-text);
}
.gb-variant--ghost {
  background: transparent;
  color: var(--button-text);
}
.gb-variant--soft {
  background: var(--button-primary-soft);
  border-color: var(--button-primary-border);
  color: var(--button-primary-text);
}
.gb-variant--link {
  background: transparent;
  color: var(--action-link);
  border: 0;
  font-weight: 500;
  height: auto;
  min-height: 24px;
  line-height: 16px;
  font-size: 13px;
  gap: 4px;
  border-radius: 0;
  box-shadow: none;
  padding: 4px 8px;
  transition: color 160ms ease, background-color 160ms ease;
}
.gb-link-tone--success {
  --action-link: var(--button-success-text);
  --action-link-hover: var(--button-success-text-hover);
  --action-link-active: var(--button-success-text-active);
  --action-soft: var(--button-success-soft);
}
.gb-link-tone--danger {
  --action-link: var(--button-danger-text);
  --action-link-hover: var(--button-danger-text-hover);
  --action-link-active: var(--button-danger-text-active);
  --action-soft: var(--button-danger-soft);
}
.gb-link-tone--warning {
  --action-link: var(--button-warning-text);
  --action-link-hover: var(--button-warning-text-hover);
  --action-link-active: var(--button-warning-text-active);
  --action-soft: var(--button-warning-soft);
}
.glass-button:hover:not(.gb-disabled) {
  background: var(--action-hover);
  border-color: var(--action-hover);
  color: var(--action-ink);
}
.gb-variant--secondary:hover:not(.gb-disabled),
.gb-variant--outline:hover:not(.gb-disabled),
.gb-variant--white:hover:not(.gb-disabled) {
  background: var(--button-surface);
  color: var(--action-link-hover);
}
.gb-variant--ghost:hover:not(.gb-disabled) {
  background: var(--button-quiet-hover);
  border-color: transparent;
  color: var(--button-text);
}
.gb-variant--soft:hover:not(.gb-disabled) {
  background: var(--action-soft);
  color: var(--action-link-hover);
  border-color: var(--button-primary-border);
}
.gb-variant--link:is(:hover, :focus-visible):not(.gb-disabled) {
  background: var(--action-soft);
  color: var(--action-link-hover);
  border: 0;
}
.gb-variant--link:active:not(.gb-disabled) {
  background: var(--action-soft);
  color: var(--action-link-active);
}
.glass-button:active:not(.gb-disabled) {
  --action-color: var(--action-active);
  --action-hover: var(--action-active);
}
.gb-variant--secondary:active:not(.gb-disabled),
.gb-variant--outline:active:not(.gb-disabled),
.gb-variant--white:active:not(.gb-disabled),
.gb-variant--soft:active:not(.gb-disabled) {
  color: var(--action-link-active);
  border-color: var(--action-active);
}
.glass-button:not(.gb-variant--link):active:not(.gb-disabled):not(:focus-visible) { transform: scale(0.98); }
.gb-active:not(.gb-variant--link) {
  box-shadow: 0 0 0 2px var(--button-primary), 0 0 0 4px var(--button-focus);
}
.glass-button.gb-disabled:not(.gb-loading) {
  background: var(--button-disabled-bg);
  color: var(--button-disabled-text);
  border-color: var(--button-border);
  box-shadow: none;
  opacity: 1;
  filter: none;
}
.gb-variant--link.gb-disabled:not(.gb-loading), .gb-variant--ghost.gb-disabled:not(.gb-loading) {
  background: transparent;
  border-color: transparent;
}

@media (hover: none), (pointer: coarse) {
  .glass-button:hover:not(.gb-disabled) { transform: none; }
  .gb-variant--link { min-height: 44px; }
}
@media (prefers-reduced-motion: reduce) {
  .glass-button { transition: none; }
  .glass-button:hover:not(.gb-disabled),
  .glass-button:not(.gb-variant--link):active:not(.gb-disabled):not(:focus-visible) { transform: none; }
}
</style>
