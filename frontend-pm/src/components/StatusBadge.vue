<template>
  <span class="badge" :class="`tone-${tone}`">
    <span v-if="dot" class="dot" aria-hidden="true"></span>{{ label }}
  </span>
</template>

<script setup>
defineProps({
  label: { type: String, required: true },
  tone: { type: String, default: 'muted' }, // cinnabar/amber/sage/slate/muted
  dot: { type: Boolean, default: false },
})
</script>

<style scoped>
/* 状态色仅用于徽标——全站纪律 */
.badge { font-weight: 500; }
.tone-cinnabar { color: var(--cinnabar); background: var(--cinnabar-wash); border-color: var(--cinnabar-line); }
.tone-amber { color: var(--amber); background: var(--amber-wash); border-color: var(--amber-line); }
.tone-sage { color: var(--sage); background: var(--sage-wash); border-color: var(--sage-line); }
.tone-slate { color: var(--slate); background: var(--slate-wash); border-color: var(--slate-line); }
.tone-muted { color: var(--ink-3); background: var(--paper-sunken); border-color: var(--hairline); }
</style>
