<template>
  <span class="qc-icon" :style="{ width: `${size}px`, height: `${size}px`, color }" aria-hidden="true">
    <component :is="is" />
  </span>
</template>

<script setup>
defineProps({
  is: { type: [Object, Function], required: true },
  size: { type: Number, default: 24 },
  color: { type: String, default: 'currentColor' },
})
</script>

<style scoped>
.qc-icon { display: inline-grid; place-items: center; flex: none; }
.qc-icon :deep(svg) { width: 100%; height: 100%; }
</style>
