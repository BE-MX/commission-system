<template>
  <div ref="root" class="dropdown">
    <div @click="toggle" class="dropdown-trigger" :class="{ open }">
      <slot name="trigger" :open="open" />
    </div>
    <Teleport to="body">
      <transition name="pop">
        <div
          v-if="open"
          ref="panel"
          class="dropdown-panel"
          :style="panelStyle"
          role="menu"
        >
          <slot :close="close" />
        </div>
      </transition>
    </Teleport>
  </div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, ref } from 'vue'

const props = defineProps({
  align: { type: String, default: 'left' }, // left / right
  width: { type: Number, default: 0 }, // 0 = 跟随触发器
})

const root = ref(null)
const panel = ref(null)
const open = ref(false)
const panelStyle = ref({})

async function toggle() {
  if (open.value) return close()
  open.value = true
  await nextTick()
  position()
  window.addEventListener('pointerdown', onOutside, true)
  window.addEventListener('keydown', onKey)
  window.addEventListener('resize', position)
  window.addEventListener('scroll', position, true)
}

function close() {
  open.value = false
  window.removeEventListener('pointerdown', onOutside, true)
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('resize', position)
  window.removeEventListener('scroll', position, true)
}

function onOutside(e) {
  if (root.value?.contains(e.target) || panel.value?.contains(e.target)) return
  close()
}
function onKey(e) {
  if (e.key === 'Escape') close()
}

function position() {
  const el = root.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const style = { position: 'fixed', top: `${rect.bottom + 6}px`, minWidth: `${rect.width}px` }
  if (props.width) style.width = `${props.width}px`
  if (props.align === 'right') {
    style.right = `${window.innerWidth - rect.right}px`
    // 从触发器一角长出（origin-aware）
    style.transformOrigin = 'top right'
  } else {
    style.left = `${rect.left}px`
    style.transformOrigin = 'top left'
  }
  panelStyle.value = style
}

onBeforeUnmount(close)
defineExpose({ close })
</script>

<style scoped>
.dropdown { display: inline-block; }
.dropdown-trigger { display: inline-block; cursor: pointer; }
.dropdown-panel {
  z-index: 900;
  background: var(--paper-raised);
  border: 1px solid var(--hairline-strong);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-overlay);
  padding: 4px;
}
.pop-enter-active { transition: opacity 150ms var(--ease-out), transform 150ms var(--ease-out); }
.pop-leave-active { transition: opacity 100ms ease, transform 100ms ease; }
.pop-enter-from, .pop-leave-to { opacity: 0; transform: scale(0.96) translateY(-3px); }
</style>
