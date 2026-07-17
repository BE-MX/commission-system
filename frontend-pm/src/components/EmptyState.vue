<template>
  <div class="empty rise">
    <svg class="empty-mark" viewBox="0 0 48 48" width="44" height="44" aria-hidden="true">
      <rect x="9" y="6" width="30" height="36" rx="2" fill="none" stroke="currentColor" stroke-width="1.4"/>
      <path d="M16 16h16M16 23h16M16 30h9" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
    </svg>
    <p class="empty-title">{{ title }}</p>
    <p v-if="hint" class="empty-hint">{{ hint }}</p>
    <slot />
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, default: '这里还是空的' },
  hint: { type: String, default: '' },
})
</script>

<style scoped>
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 72px 24px;
  color: var(--ink-4);
  text-align: center;
}
.empty-title { color: var(--ink-3); font-size: 14px; }
.empty-hint { color: var(--ink-4); font-size: 12.5px; }
</style>
