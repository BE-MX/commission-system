<template>
  <nav class="workspace-tabs" role="tablist" aria-label="AI 工作台">
    <button
      v-if="canUseImage"
      class="workspace-tab"
      :class="{ 'is-active': route.name === 'DesignImageStudio' }"
      type="button"
      role="tab"
      :aria-selected="route.name === 'DesignImageStudio'"
      @click="open('DesignImageStudio')"
    >
      <el-icon aria-hidden="true"><Picture /></el-icon>
      AI 生图
    </button>
    <button
      v-if="canUseChat"
      class="workspace-tab"
      :class="{ 'is-active': route.name === 'DesignAiChat' }"
      type="button"
      role="tab"
      :aria-selected="route.name === 'DesignAiChat'"
      @click="open('DesignAiChat')"
    >
      <el-icon aria-hidden="true"><ChatLineRound /></el-icon>
      方案对话
    </button>
  </nav>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ChatLineRound, Picture } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const canUseImage = computed(() => auth.hasPermission('design_image:read'))
const canUseChat = computed(() => auth.hasPermission('ai_chat:read'))

function open(name) {
  if (name === 'DesignImageStudio' && !canUseImage.value) return
  if (name === 'DesignAiChat' && !canUseChat.value) return
  if (route.name !== name) router.push({ name })
}
</script>

<style scoped>
.workspace-tabs {
  position: relative;
  z-index: 2;
  display: inline-flex;
  align-self: center;
  gap: 4px;
  padding: 4px;
  border: 1px solid var(--dash-glass-border);
  border-radius: 12px;
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-highlight), var(--card-shadow);
}

.workspace-tab {
  display: inline-flex;
  min-height: 36px;
  align-items: center;
  gap: 7px;
  padding: 0 16px;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-family: var(--font-display);
  font-size: 13px;
  font-weight: 600;
  transition:
    background-color 180ms ease,
    box-shadow 180ms ease,
    color 180ms ease,
    transform 140ms var(--ease-out-strong);
}

.workspace-tab.is-active {
  background: var(--dash-glass-bg-strong);
  color: var(--color-primary);
  box-shadow: var(--dash-glass-highlight), var(--card-shadow);
}

.workspace-tab:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

.workspace-tab:active { transform: scale(0.96); }

@media (hover: hover) and (pointer: fine) {
  .workspace-tab:not(.is-active):hover {
    color: var(--text-primary);
    box-shadow: var(--card-shadow);
  }
}

@media (prefers-reduced-motion: reduce) {
  .workspace-tab { transition: none; }
  .workspace-tab:active { transform: none; }
}
</style>
