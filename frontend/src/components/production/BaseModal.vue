<template>
  <Teleport to="body">
    <Transition name="db-modal-fade">
      <div
        v-if="modelValue"
        class="db-modal-overlay"
        @click.self="close"
      >
        <Transition name="db-modal-slide">
          <div
            v-if="modelValue"
            class="db-modal"
            :style="{ width: width, maxWidth: '95vw' }"
            role="dialog"
            aria-modal="true"
            :aria-label="title"
          >
            <!-- 头部 -->
            <div class="db-modal__header">
              <span class="db-modal__title">{{ title }}</span>
              <button class="db-modal__close" @click="close" aria-label="关闭">
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                  <path d="M3 3L13 13M13 3L3 13" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                </svg>
              </button>
            </div>

            <!-- 内容区 -->
            <div class="db-modal__body">
              <slot />
            </div>
          </div>
        </Transition>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title:      { type: String,  default: '' },
  width:      { type: String,  default: '680px' },
})

const emit = defineEmits(['update:modelValue'])

function close() {
  emit('update:modelValue', false)
}
</script>

<style scoped>
/* overlay */
.db-modal-overlay {
  position: fixed;
  inset: 0;
  background: var(--db-overlay-bg);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}

/* modal 容器 */
.db-modal {
  background: var(--db-card-bg);
  border: 1px solid var(--db-border);
  border-radius: 12px;
  box-shadow: 0 20px 60px var(--db-shadow-heavy);
  display: flex;
  flex-direction: column;
  max-height: 80vh;
  overflow: hidden;
}

/* 头部 */
.db-modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--db-border);
  flex-shrink: 0;
}

.db-modal__title {
  font-size: 15px;
  font-weight: 700;
  color: var(--db-text-primary);
}

.db-modal__close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: 1px solid var(--db-border);
  background: transparent;
  color: var(--db-text-muted);
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}

.db-modal__close:hover {
  background: var(--db-hover-bg);
  color: var(--db-text-primary);
  border-color: var(--db-accent-red);
}

/* 内容区 */
.db-modal__body {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.db-modal__body::-webkit-scrollbar {
  width: 4px;
}
.db-modal__body::-webkit-scrollbar-track {
  background: transparent;
}
.db-modal__body::-webkit-scrollbar-thumb {
  background: var(--db-scrollbar);
  border-radius: 2px;
}

/* 动画：overlay fade */
.db-modal-fade-enter-active,
.db-modal-fade-leave-active {
  transition: opacity 0.22s ease;
}
.db-modal-fade-enter-from,
.db-modal-fade-leave-to {
  opacity: 0;
}

/* 动画：modal slide-up */
.db-modal-slide-enter-active {
  transition: transform 0.25s cubic-bezier(0.34, 1.2, 0.64, 1), opacity 0.22s ease;
}
.db-modal-slide-leave-active {
  transition: transform 0.18s ease, opacity 0.18s ease;
}
.db-modal-slide-enter-from {
  transform: translateY(24px) scale(0.97);
  opacity: 0;
}
.db-modal-slide-leave-to {
  transform: translateY(16px) scale(0.97);
  opacity: 0;
}
</style>
