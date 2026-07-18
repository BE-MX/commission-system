<template>
  <!-- 顶栏品牌徽标：LeShine logo 圆形徽章（金面墨环，与门牌页同款） -->
  <img
    class="seal"
    src="/seal-logo.png"
    :width="size"
    :height="size"
    alt="LeShine Hair"
  />
</template>

<script setup>
defineProps({ size: { type: [Number, String], default: 34 } })
</script>

<style scoped>
.seal {
  display: block;
  border-radius: 50%;
  flex-shrink: 0;
}
</style>
