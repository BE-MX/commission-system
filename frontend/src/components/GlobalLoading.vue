<template>
  <Teleport to="body">
    <Transition name="loading-fade">
      <div v-if="visible" class="global-loading-overlay" @click.stop @mousedown.stop>
        <div class="loading-content">
          <div class="loader">
            <div class="loader-ring"></div>
            <div class="loader-ring"></div>
            <div class="loader-ring"></div>
            <div class="loader-dot"></div>
          </div>
          <p v-if="text" class="loading-text">{{ text }}</p>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { useLoading } from '@/composables/useLoading'
const { visible, text } = useLoading()
</script>

<style>
.global-loading-overlay {
  position: fixed;
  inset: 0;
  z-index: 99999;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(26, 24, 22, 0.35);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  cursor: wait;
}

.loading-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 28px;
}

/* --- Concentric rings loader --- */
.loader {
  position: relative;
  width: 64px;
  height: 64px;
}

.loader-ring {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  border: 2.5px solid transparent;
}

.loader-ring:nth-child(1) {
  border-top-color: #D4941C;
  animation: loader-spin 1.2s cubic-bezier(0.5, 0, 0.5, 1) infinite;
}

.loader-ring:nth-child(2) {
  inset: 7px;
  border-right-color: #F5CB5C;
  animation: loader-spin 1.6s cubic-bezier(0.5, 0, 0.5, 1) infinite reverse;
}

.loader-ring:nth-child(3) {
  inset: 14px;
  border-bottom-color: rgba(212, 148, 28, 0.45);
  animation: loader-spin 2s cubic-bezier(0.5, 0, 0.5, 1) infinite;
}

.loader-dot {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 6px;
  height: 6px;
  margin: -3px 0 0 -3px;
  border-radius: 50%;
  background: #D4941C;
  animation: loader-pulse 1.2s ease-in-out infinite;
}

@keyframes loader-spin {
  0%   { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

@keyframes loader-pulse {
  0%, 100% { opacity: 0.3; transform: scale(0.8); }
  50%      { opacity: 1;   transform: scale(1.3); }
}

/* --- Text --- */
.loading-text {
  margin: 0;
  font-family: var(--font-display, 'Outfit', sans-serif);
  font-size: 14px;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.88);
  letter-spacing: 0.06em;
  text-shadow: 0 1px 4px rgba(0, 0, 0, 0.3);
  animation: text-breathe 2s ease-in-out infinite;
}

@keyframes text-breathe {
  0%, 100% { opacity: 0.7; }
  50%      { opacity: 1; }
}

/* --- Transition --- */
.loading-fade-enter-active {
  transition: opacity 0.2s ease-out;
}
.loading-fade-leave-active {
  transition: opacity 0.35s ease-in;
}
.loading-fade-enter-from,
.loading-fade-leave-to {
  opacity: 0;
}
</style>
