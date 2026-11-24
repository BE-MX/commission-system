<template>
  <li class="draft-row" :class="{ open, dragging: dragOffset !== null }" :style="{ '--draft-action-width': `${ACTION_WIDTH}px` }"
    @touchstart.passive="startTouch" @touchmove.passive="moveTouch" @touchend="endTouch" @touchcancel="cancelTouch">
    <div class="draft-track" :style="{ transform: dragOffset === null ? undefined : `translateX(${dragOffset}px)` }"
      @keydown.esc.stop="closeActions">
      <button ref="card" class="draft-card" type="button" :disabled="disabled" :aria-disabled="busy || undefined" @click="activateCard">
        <span class="draft-main">
          <span class="draft-eyebrow">工厂单据{{ showUnconfirmed ? ' · 待确认' : '' }}</span>
          <strong class="draft-no" :class="{ pending: !draftNumber }">{{ draftNumber || '编号待确认' }}</strong>
          <small>{{ draft.inbound_no }} · {{ deliveryDate(draft) }}</small>
        </span>
        <span class="pill" :class="'tone-' + noteTone(draft)">{{ noteStatus(draft) }}</span>
        <ArrowRight class="chevron" />
      </button>
      <button class="draft-delete" type="button" :disabled="disabled" :aria-disabled="busy || undefined"
        :aria-label="`删除草稿 ${draft.inbound_no}`" @click="activateDelete">
        <Delete aria-hidden="true" />删除
      </button>
    </div>
  </li>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ArrowRight, Delete } from '@element-plus/icons-vue'
import { deliveryDate, noteStatus, noteTone } from '../inboundLabels'

const props = defineProps({
  draft: { type: Object, required: true },
  open: Boolean,
  disabled: Boolean,
  busy: Boolean,
})
const emit = defineEmits(['reveal', 'open', 'remove'])

const ACTION_WIDTH = 80
const DRAG_SLOP = 8
const card = ref(null)
const dragOffset = ref(null)
const draftNumber = computed(() => props.draft.delivery_no || props.draft.recognized_delivery_no)
const showUnconfirmed = computed(() => !props.draft.delivery_no && props.draft.recognized_delivery_no)
let gesture = null

function startTouch(event) {
  cancelTouch()
  if (props.disabled || props.busy || event.touches.length !== 1) return
  const button = event.target.closest('button')
  if (!button) return
  const touch = event.touches[0]
  gesture = { id: touch.identifier, x: touch.clientX, y: touch.clientY, onCard: button === card.value, mode: 'tap' }
}

function moveTouch(event) {
  if (!gesture || gesture.mode === 'scroll') return
  const touch = event.touches[0]
  if (event.touches.length !== 1 || touch.identifier !== gesture.id) {
    cancelTouch()
    return
  }
  const dx = touch.clientX - gesture.x
  const dy = touch.clientY - gesture.y
  if (gesture.mode === 'tap') {
    if (Math.max(Math.abs(dx), Math.abs(dy)) < DRAG_SLOP) return
    gesture.mode = gesture.onCard && Math.abs(dx) > Math.abs(dy) ? 'swipe' : 'scroll'
  }
  if (gesture.mode !== 'swipe') return
  const offset = (props.open ? -ACTION_WIDTH : 0) + dx
  dragOffset.value = Math.max(-ACTION_WIDTH, Math.min(0, offset))
}

function endTouch(event) {
  if (!gesture) return
  const { id, x, y, onCard, mode } = gesture
  const offset = dragOffset.value
  cancelTouch()
  const touch = event.changedTouches[0]
  if (event.touches.length || touch?.identifier !== id) return
  if (event.cancelable) event.preventDefault()
  if (props.busy || props.disabled) return
  if (mode === 'swipe') emit('reveal', offset <= -ACTION_WIDTH / 2)
  if (mode === 'tap' && event.cancelable && Math.max(Math.abs(touch.clientX - x), Math.abs(touch.clientY - y)) < DRAG_SLOP) {
    if (onCard) activateCard()
    else activateDelete()
  }
}

function cancelTouch() {
  gesture = null
  dragOffset.value = null
}

function activateCard() {
  if (props.busy) return
  if (props.open) emit('reveal', false)
  else emit('open')
}

function activateDelete() {
  if (!props.busy) emit('remove')
}

function closeActions() {
  emit('reveal', false)
  card.value.focus()
}
</script>

<style src="../pills.css" scoped></style>
<style scoped>
.draft-row{min-width:0;overflow:hidden;overflow:clip}
.draft-track{position:relative;transform:translateX(0);transition:transform 150ms cubic-bezier(.23,1,.32,1)}
.draft-row.open .draft-track,.draft-row:has(.draft-delete:focus-visible) .draft-track{transform:translateX(calc(-1 * var(--draft-action-width)))}
.draft-row.dragging .draft-track{transition:none}
.draft-row:has(:focus-visible) .draft-track{transition:none}
.draft-card{width:100%;display:flex;align-items:center;gap:12px;padding:16px 14px 16px 18px;border:1px solid var(--border-color);border-radius:18px;background:var(--card-bg);color:inherit;font:inherit;text-align:left;cursor:pointer;user-select:none;touch-action:pan-y pinch-zoom;transition:border-color 160ms ease}
.draft-main{flex:1;min-width:0;display:grid;gap:2px}
.draft-eyebrow{font-size:11px;color:var(--text-secondary)}
.draft-no{font-family:var(--font-mono,ui-monospace,monospace);font-size:20px;font-weight:750;letter-spacing:.02em;overflow-wrap:anywhere}
.draft-no.pending{font-family:inherit;font-size:16px;color:var(--text-secondary)}
.draft-main small{font-size:12px;color:var(--text-secondary)}
.chevron{width:16px;height:16px;color:var(--text-tertiary)}
.draft-delete{position:absolute;inset:0 auto 0 calc(100% + 6px);width:calc(var(--draft-action-width) - 6px);display:grid;place-content:center;justify-items:center;gap:4px;border:1px solid var(--button-danger-border);border-radius:18px;background:var(--button-danger-soft);color:var(--button-danger-text);font:inherit;font-size:14px;font-weight:700;cursor:pointer;touch-action:manipulation}
.draft-delete svg{width:18px;height:18px}
.draft-delete:disabled,.draft-card:disabled{cursor:default}
.draft-row:not(.dragging) .draft-card:active:not(:disabled){border-color:var(--button-primary-border)}
.draft-delete:active:not(:disabled){color:var(--button-danger-text-active);border-color:var(--button-danger-active)}
.draft-card:focus-visible,.draft-delete:focus-visible{outline:3px solid var(--button-focus,var(--button-primary));outline-offset:-3px}
@media (hover:hover) and (pointer:fine){
  .draft-card:hover:not(:disabled){border-color:var(--button-primary-border)}
  .draft-delete:hover:not(:disabled){color:var(--button-danger-text-hover);border-color:var(--button-danger-hover)}
}
@media (prefers-reduced-motion:reduce){
  .draft-track,.draft-card{transition:none}
}
</style>
