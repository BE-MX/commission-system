<template>
  <button
    :class="btnClasses"
    :disabled="disabled || loading"
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

  /** Only effective when variant="link". Values: primary | success | danger */
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
  if (props.active)          c.push('gb-active')

  if (props.shadow !== false && !props.disabled) {
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
  transition: all 0.2s ease-out;
  user-select: none;
  font-family: var(--font-display);
  font-weight: 600;
  cursor: pointer;
  border: none;
  outline: none;
  white-space: nowrap;
  line-height: 1;
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
  opacity: 0.5;
  cursor: not-allowed;
  pointer-events: none;
  filter: grayscale(0.3);
}

.gb-active {
  box-shadow: 0 0 0 2px rgba(212, 148, 28, 0.4), 0 0 0 4px rgba(212, 148, 28, 0.1);
}

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

/* primary */
.gb-variant--primary {
  background: linear-gradient(135deg, var(--color-primary), var(--color-primary-hover));
  color: #fff;
  border: 1px solid rgba(212,148,28,0.3);
}
.gb-variant--primary:hover:not(.gb-disabled) {
  background: linear-gradient(135deg, #c4891a, #a87616);
  box-shadow: 0 4px 16px rgba(212,148,28,0.25);
  transform: translateY(-1px);
}
.gb-variant--primary:active:not(.gb-disabled) {
  transform: scale(0.98);
}

/* secondary */
.gb-variant--secondary {
  background: rgba(255,255,255,0.7);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
}
.gb-variant--secondary:hover:not(.gb-disabled) {
  background: rgba(255,255,255,0.9);
  border-color: rgba(212,148,28,0.3);
  box-shadow: 0 2px 12px rgba(212,148,28,0.08);
  color: var(--text-primary);
}
.gb-variant--secondary:active:not(.gb-disabled) {
  transform: scale(0.98);
}

/* outline */
.gb-variant--outline {
  background: transparent;
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
}
.gb-variant--outline:hover:not(.gb-disabled) {
  background: rgba(255,255,255,0.6);
  border-color: rgba(212,148,28,0.5);
  color: var(--color-primary);
  backdrop-filter: blur(8px);
}
.gb-variant--outline:active:not(.gb-disabled) {
  transform: scale(0.98);
}

/* ghost */
.gb-variant--ghost {
  background: transparent;
  color: var(--text-secondary);
  border: 1px solid transparent;
}
.gb-variant--ghost:hover:not(.gb-disabled) {
  background: rgba(240,242,247,0.8);
  color: var(--text-primary);
  backdrop-filter: blur(4px);
}
.gb-variant--ghost:active:not(.gb-disabled) {
  transform: scale(0.98);
}

/* soft */
.gb-variant--soft {
  background: var(--color-gold-soft);
  color: var(--color-gold-muted);
  border: 1px solid #f5e0b5;
}
.gb-variant--soft:hover:not(.gb-disabled) {
  background: #fef3e0;
  border-color: #e8cc8e;
  box-shadow: 0 2px 8px rgba(212,148,28,0.1);
}
.gb-variant--soft:active:not(.gb-disabled) {
  transform: scale(0.98);
}

/* link */
.gb-variant--link {
  background: transparent;
  color: var(--color-primary);
  border: none;
  font-weight: 500;
  text-decoration: none;
  height: auto;
  padding: 4px 8px;
}
.gb-variant--link:hover:not(.gb-disabled) {
  text-decoration: underline;
  text-underline-offset: 4px;
  color: var(--color-primary-hover);
  background: var(--color-primary-light);
}
.gb-variant--link:active:not(.gb-disabled) {
  transform: scale(0.98);
}

/* link tone overrides */
.gb-variant--link.gb-link-tone--success {
  color: var(--color-success);
}
.gb-variant--link.gb-link-tone--success:hover:not(.gb-disabled) {
  color: var(--color-success-hover);
  background: var(--color-success-bg);
}

.gb-variant--link.gb-link-tone--danger {
  color: var(--color-danger-hover);
}
.gb-variant--link.gb-link-tone--danger:hover:not(.gb-disabled) {
  color: var(--color-danger-deep);
  background: var(--color-danger-bg);
}

/* danger */
.gb-variant--danger {
  background: linear-gradient(135deg, var(--color-danger), var(--color-danger-hover));
  color: #fff;
  border: 1px solid rgba(220,53,69,0.3);
}
.gb-variant--danger:hover:not(.gb-disabled) {
  background: linear-gradient(135deg, var(--color-danger-hover), var(--color-danger-deep));
  box-shadow: 0 4px 16px rgba(220,53,69,0.2);
  transform: translateY(-1px);
}
.gb-variant--danger:active:not(.gb-disabled) {
  transform: scale(0.98);
}

/* success */
.gb-variant--success {
  background: linear-gradient(135deg, var(--color-success), var(--color-success-hover));
  color: #fff;
  border: 1px solid rgba(45,159,111,0.3);
}
.gb-variant--success:hover:not(.gb-disabled) {
  background: linear-gradient(135deg, var(--color-success-hover), var(--color-success-text));
  box-shadow: 0 4px 16px rgba(45,159,111,0.2);
  transform: translateY(-1px);
}
.gb-variant--success:active:not(.gb-disabled) {
  transform: scale(0.98);
}

/* warning */
.gb-variant--warning {
  background: linear-gradient(135deg, #f59e0b, #d97706);
  color: #fff;
  border: 1px solid rgba(245,158,11,0.3);
}
.gb-variant--warning:hover:not(.gb-disabled) {
  background: linear-gradient(135deg, #d97706, #b45309);
  box-shadow: 0 4px 16px rgba(245,158,11,0.2);
  transform: translateY(-1px);
}
.gb-variant--warning:active:not(.gb-disabled) {
  transform: scale(0.98);
}

/* info */
.gb-variant--info {
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  color: #fff;
  border: 1px solid rgba(59,130,246,0.3);
}
.gb-variant--info:hover:not(.gb-disabled) {
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  box-shadow: 0 4px 16px rgba(59,130,246,0.2);
  transform: translateY(-1px);
}
.gb-variant--info:active:not(.gb-disabled) {
  transform: scale(0.98);
}

/* white */
.gb-variant--white {
  background: rgba(255,255,255,0.8);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  color: var(--text-primary);
  border: 1px solid rgba(255,255,255,0.6);
  box-shadow: 0 2px 8px rgba(0,0,0,0.06), inset 0 1px 0 rgba(255,255,255,0.8);
}
.gb-variant--white:hover:not(.gb-disabled) {
  background: rgba(255,255,255,0.95);
  box-shadow: 0 4px 20px rgba(0,0,0,0.08), inset 0 1px 0 rgba(255,255,255,0.9);
  border-color: rgba(255,255,255,0.8);
}
.gb-variant--white:active:not(.gb-disabled) {
  transform: scale(0.98);
}
</style>
