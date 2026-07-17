<template>
  <Teleport to="body">
    <transition name="modal">
      <div v-if="modelValue" class="modal-mask" @pointerdown.self="close">
        <div class="modal" role="alertdialog" :aria-label="title">
          <h3 class="modal-title">{{ title }}</h3>
          <div class="modal-body"><slot>{{ message }}</slot></div>
          <footer class="modal-foot">
            <slot name="footer">
              <button class="btn" type="button" @click="close">{{ cancelText }}</button>
              <button
                class="btn"
                :class="danger ? 'btn-accent' : 'btn-primary'"
                type="button"
                @click="confirm"
              >{{ confirmText }}</button>
            </slot>
          </footer>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<script setup>
const props = defineProps({
  modelValue: Boolean,
  title: { type: String, default: '确认' },
  message: { type: String, default: '' },
  confirmText: { type: String, default: '确认' },
  cancelText: { type: String, default: '取消' },
  danger: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'confirm'])
function close() { emit('update:modelValue', false) }
function confirm() { emit('confirm'); close() }
</script>

<style scoped>
.modal-mask {
  position: fixed;
  inset: 0;
  z-index: 850;
  background: rgba(28, 27, 25, 0.3);
  backdrop-filter: blur(2px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.modal {
  width: min(420px, 100%);
  background: var(--paper);
  border: 1px solid var(--hairline-strong);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-overlay);
  padding: 26px 26px 20px;
  transform-origin: center; /* modal 保持中心缩放（popover 才贴触发器） */
}
.modal-title {
  font-family: var(--font-serif);
  font-size: 18px;
  margin-bottom: 10px;
}
.modal-body {
  color: var(--ink-2);
  font-size: 13.5px;
  line-height: 1.7;
}
.modal-foot {
  margin-top: 22px;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
.modal-enter-active { transition: opacity 180ms ease; }
.modal-enter-active .modal { transition: transform 200ms var(--ease-out), opacity 200ms var(--ease-out); }
.modal-leave-active { transition: opacity 130ms ease; }
.modal-leave-active .modal { transition: transform 130ms ease, opacity 130ms ease; }
.modal-enter-from, .modal-leave-to { opacity: 0; }
.modal-enter-from .modal { opacity: 0; transform: scale(0.95) translateY(8px); }
.modal-leave-to .modal { opacity: 0; transform: scale(0.98) translateY(4px); }
</style>
