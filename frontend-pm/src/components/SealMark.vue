<template>
  <!-- 顶栏品牌徽标：LeShine logo 圆形徽章（金面墨环，与门牌页同款） -->
  <img
    class="seal"
    :src="sealUrl"
    :width="size"
    :height="size"
    alt="LeShine Hair"
  />
</template>

<script setup>
// public 资产要带构建 base 前缀，否则内网 /pm/ 入口下会落到主站根路径变坏图
const sealUrl = import.meta.env.BASE_URL + 'seal-logo.png'
defineProps({ size: { type: [Number, String], default: 34 } })
</script>

<style scoped>
.seal {
  display: block;
  border-radius: 50%;
  flex-shrink: 0;
}
</style>
