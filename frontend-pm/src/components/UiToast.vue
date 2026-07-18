<template>
  <Teleport to="body">
    <div class="toast-stack" aria-live="polite">
      <TransitionGroup name="toast">
        <div v-for="t in toastStore.items" :key="t.id" class="toast" :class="`toast-${t.kind}`">
          <span class="toast-mark" aria-hidden="true">
            <svg v-if="t.kind === 'success'" viewBox="0 0 12 12" width="11" height="11"><path d="M2 6.2 4.8 9 10 3.4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
            <svg v-else-if="t.kind === 'error'" viewBox="0 0 12 12" width="11" height="11"><path d="M6 2.5v4.2M6 9.4v.1" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
            <svg v-else viewBox="0 0 12 12" width="11" height="11"><circle cx="6" cy="6" r="4.4" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M6 5.4v3M6 3.6v.1" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>
          </span>
          <span>{{ t.message }}</span>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<script setup>
import { toastStore } from '../stores/toast.js'
</script>

<style scoped>
.toast-stack {
  position: fixed;
  bottom: 28px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 1000;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  pointer-events: none;
}
.toast {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 9px 16px;
  background: var(--ink);
  color: var(--paper);
  font-size: 13px;
  border-radius: var(--radius);
  box-shadow: var(--shadow-overlay);
  max-width: min(480px, 90vw);
}
.toast-error { background: var(--danger-deep); }
.toast-mark { display: inline-flex; flex-shrink: 0; }

/* 空间一致性：从下方进入、向下方离开 */
.toast-enter-active { transition: opacity var(--dur-med) var(--ease-out), transform var(--dur-med) var(--ease-out); }
.toast-leave-active { transition: opacity 160ms ease, transform 160ms ease; }
.toast-enter-from { opacity: 0; transform: translateY(12px) scale(0.97); }
.toast-leave-to { opacity: 0; transform: translateY(8px) scale(0.98); }
</style>
