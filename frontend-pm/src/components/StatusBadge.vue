<template>
  <span class="badge" :class="`tone-${tone}`">
    <span v-if="dot" class="dot" aria-hidden="true"></span>{{ label }}
  </span>
</template>

<script setup>
defineProps({
  label: { type: String, required: true },
  tone: { type: String, default: 'muted' }, // gold/ink/danger/amber/sage/slate/muted
  dot: { type: Boolean, default: false },
})
</script>

<style scoped>
/* 状态色仅用于徽标——全站纪律 */
.badge { font-weight: 500; }
.tone-gold { color: var(--gold-deep); background: var(--gold-wash); border-color: var(--gold-line); }
.tone-ink { color: var(--paper); background: var(--ink); border-color: var(--ink); }
.tone-ink .dot { background: var(--gold); }
.tone-danger { color: var(--danger); background: var(--danger-wash); border-color: var(--danger-line); }
.tone-amber { color: var(--amber); background: var(--amber-wash); border-color: var(--amber-line); }
.tone-sage { color: var(--sage); background: var(--sage-wash); border-color: var(--sage-line); }
.tone-slate { color: var(--slate); background: var(--slate-wash); border-color: var(--slate-line); }
.tone-muted { color: var(--ink-3); background: var(--paper-sunken); border-color: var(--hairline); }
</style>
