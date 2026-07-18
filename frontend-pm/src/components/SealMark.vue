<template>
  <!-- 顶栏印鉴：LeShine logo 金卡同款关系——金面 + 墨环 + 墨字 -->
  <svg
    class="seal"
    :width="size"
    :height="size"
    viewBox="0 0 48 48"
    role="img"
    aria-label="莱莎项目站印鉴"
  >
    <circle cx="24" cy="24" r="21.2" fill="var(--gold)" stroke="var(--ink)" :stroke-width="2.2" />
    <circle cx="24" cy="24" r="16.4" fill="none" stroke="var(--ink)" :stroke-width="0.8" />
    <text
      x="24"
      y="30.5"
      text-anchor="middle"
      font-size="17.5"
      fill="var(--ink)"
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
  flex-shrink: 0;
}
</style>
