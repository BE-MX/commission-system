<template>
  <div ref="root" class="text-color-picker">
    <button
      class="color-trigger"
      type="button"
      :aria-label="label"
      aria-haspopup="menu"
      :aria-expanded="open"
      :title="label"
      @mousedown.prevent
      @click.stop="toggle"
    >
      <span aria-hidden="true">{{ highlight ? 'Aa' : 'A' }}</span>
      <i :style="{ backgroundColor: currentOption.cssColor }" />
    </button>
    <div v-if="open" class="color-menu" role="menu" :aria-label="'选择' + label">
      <button
        v-for="option in options"
        :key="option.tone || 'default'"
        class="color-option"
        type="button"
        role="menuitemradio"
        :aria-checked="currentTone === option.tone"
        @mousedown.prevent
        @click.stop="select(option.tone)"
      >
        <span class="color-swatch" :style="{ backgroundColor: option.cssColor }" aria-hidden="true" />
        <span>{{ option.label }}</span>
        <span class="selected-check" aria-hidden="true">{{ currentTone === option.tone ? '✓' : '' }}</span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { TEXT_COLOR_OPTIONS, applyTextColor, normalizeTextColorTone } from './TextColorMark.js'
import { HIGHLIGHT_COLORS } from './knowledgeAuthoring.js'

const props = defineProps({
  editor: { type: Object, required: true },
  version: { type: Number, default: 0 },
  highlight: Boolean,
})

const root = ref(null)
const open = ref(false)
const label = computed(() => props.highlight ? '文字高亮' : '字体颜色')
const mark = computed(() => props.highlight ? 'knowledgeHighlight' : 'textColor')
const options = computed(() => props.highlight
  ? TEXT_COLOR_OPTIONS.map(option => ({ ...option, cssColor: HIGHLIGHT_COLORS[option.tone] || 'transparent' }))
  : TEXT_COLOR_OPTIONS)
const currentTone = computed(() => {
  void props.version
  if (!props.editor.isActive(mark.value)) return null
  return normalizeTextColorTone(props.editor.getAttributes(mark.value).tone)
})
const currentOption = computed(() => (
  options.value.find(option => option.tone === currentTone.value) || options.value[0]
))

function toggle() {
  open.value = !open.value
}

function close() {
  open.value = false
}

function select(tone) {
  if (props.highlight) {
    const chain = props.editor.chain().focus()
    if (tone) chain.setMark('knowledgeHighlight', { tone }).run()
    else chain.unsetMark('knowledgeHighlight').run()
  } else {
    applyTextColor(props.editor, tone)
  }
  close()
}

function handleOutside(event) {
  if (open.value && !root.value?.contains(event.target)) close()
}

function handleKeydown(event) {
  if (open.value && event.key === 'Escape') {
    event.stopPropagation()
    close()
  }
}

onMounted(() => {
  document.addEventListener('pointerdown', handleOutside)
  document.addEventListener('keydown', handleKeydown)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handleOutside)
  document.removeEventListener('keydown', handleKeydown)
})
</script>

<style scoped>
.text-color-picker { position: relative; }
.color-trigger { position: relative; display: grid; width: 30px; min-width: 30px; height: 30px; place-items: center; padding: 0 6px 4px; border: 1px solid transparent; border-radius: 6px; color: var(--text-secondary); background: transparent; cursor: pointer; font: 600 14px/1 var(--font-body); transition: color 120ms ease, background-color 120ms ease, transform 120ms cubic-bezier(.23,1,.32,1); }
.color-trigger i { position: absolute; right: 6px; bottom: 3px; left: 6px; height: 3px; border-radius: 2px; }
.color-trigger:focus-visible, .color-option:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 1px; }
.color-menu { position: absolute; z-index: 30; top: calc(100% + 6px); left: 0; display: grid; min-width: 142px; gap: 2px; padding: 6px; border: 1px solid var(--border-color); border-radius: 9px; background: var(--surface-card, var(--card-bg)); box-shadow: var(--card-shadow-hover); }
.color-option { display: grid; width: 100%; height: 32px; grid-template-columns: 18px minmax(0, 1fr) 14px; align-items: center; gap: 8px; padding: 0 8px; border: 0; border-radius: 6px; color: var(--text-secondary); background: transparent; cursor: pointer; font: inherit; font-size: 12px; text-align: left; transition: color 120ms ease, background-color 120ms ease, transform 120ms cubic-bezier(.23,1,.32,1); }
.color-option[aria-checked='true'] { color: var(--text-primary); background: var(--color-primary-light); font-weight: 600; }
.color-swatch { width: 16px; height: 16px; border: 1px solid var(--border-hover); border-radius: 50%; }
.selected-check { color: var(--color-primary-text); text-align: right; }
@media (hover: hover) and (pointer: fine) {
  .color-trigger:hover, .color-option:hover { color: var(--color-primary-text); background: var(--color-primary-light); }
  .color-trigger:active:not(:focus-visible), .color-option:active:not(:focus-visible) { transform: scale(.97); }
}
@media (prefers-reduced-motion: reduce) {
  .color-trigger, .color-option { transition: color 120ms ease, background-color 120ms ease; }
  .color-trigger:active, .color-option:active { transform: none; }
}
</style>
