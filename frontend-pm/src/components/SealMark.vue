<template>
  <svg
    class="seal"
    :width="size"
    :height="size"
    viewBox="0 0 48 48"
    role="img"
    aria-label="莱莎项目站印鉴"
  >
    <circle cx="24" cy="24" r="21.2" fill="none" stroke="currentColor" :stroke-width="2.6" />
    <circle cx="24" cy="24" r="16.4" fill="none" stroke="currentColor" :stroke-width="0.9" />
    <text
      x="24"
      y="30.5"
      text-anchor="middle"
      font-size="17.5"
      fill="currentColor"
      :style="{ fontFamily: 'var(--font-serif)' }"
    >莱</text>
  </svg>
</template>

<script setup>
defineProps({ size: { type: [Number, String], default: 34 } })
</script>

<style scoped>
.seal {
  display: block;
  color: var(--cinnabar);
  flex-shrink: 0;
}
</style>
