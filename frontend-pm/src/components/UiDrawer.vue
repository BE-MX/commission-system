<template>
  <Teleport to="body">
    <transition name="drawer">
      <div v-if="modelValue" class="drawer-mask" @pointerdown.self="close">
        <aside class="drawer" role="dialog" :aria-label="title" :style="{ width: `${width}px` }">
          <header class="drawer-head">
            <div>
              <div class="drawer-eyebrow" v-if="eyebrow">{{ eyebrow }}</div>
              <h3 class="drawer-title">{{ title }}</h3>
            </div>
            <button class="drawer-close" type="button" aria-label="关闭" @click="close">
              <svg viewBox="0 0 14 14" width="13" height="13"><path d="M2 2l10 10M12 2 2 12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
            </button>
          </header>
          <div class="drawer-body">
            <slot />
          </div>
          <footer v-if="$slots.footer" class="drawer-foot">
            <slot name="footer" />
          </footer>
        </aside>
      </div>
    </transition>
  </Teleport>
</template>

<script setup>
import { watch } from 'vue'

const props = defineProps({
  modelValue: Boolean,
  title: { type: String, default: '' },
  eyebrow: { type: String, default: '' },
  width: { type: Number, default: 460 },
})
const emit = defineEmits(['update:modelValue'])

function close() {
  emit('update:modelValue', false)
}

watch(
  () => props.modelValue,
  (v) => {
    document.body.style.overflow = v ? 'hidden' : ''
  }
)
</script>

<style scoped>
.drawer-mask {
  position: fixed;
  inset: 0;
  z-index: 800;
  background: rgba(28, 27, 25, 0.28);
  backdrop-filter: blur(2px);
}
.drawer {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  max-width: 92vw;
  background: var(--paper);
  border-left: 1px solid var(--hairline-strong);
  box-shadow: var(--shadow-overlay);
  display: flex;
  flex-direction: column;
}
.drawer-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 26px 28px 18px;
  border-bottom: 1px solid var(--hairline);
}
.drawer-eyebrow {
  font-size: 11px;
  letter-spacing: 0.16em;
  color: var(--ink-3);
  font-family: var(--font-mono);
  margin-bottom: 6px;
}
.drawer-title {
  font-family: var(--font-serif);
  font-size: 20px;
}
.drawer-close {
  padding: 6px;
  color: var(--ink-3);
  border-radius: var(--radius);
  transition: color var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out), transform var(--dur-fast) var(--ease-out);
}
.drawer-close:active { transform: scale(0.95); }
@media (hover: hover) and (pointer: fine) {
  .drawer-close:hover { color: var(--ink); background: var(--paper-sunken); }
}
.drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 24px 28px;
}
.drawer-foot {
  padding: 16px 28px 20px;
  border-top: 1px solid var(--hairline);
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.drawer-enter-active { transition: opacity var(--dur-med) ease; }
.drawer-enter-active .drawer { transition: transform 300ms var(--ease-drawer); }
.drawer-leave-active { transition: opacity 180ms ease; }
.drawer-leave-active .drawer { transition: transform 200ms var(--ease-in-out); }
.drawer-enter-from, .drawer-leave-to { opacity: 0; }
.drawer-enter-from .drawer, .drawer-leave-to .drawer { transform: translateX(48px); }
</style>
