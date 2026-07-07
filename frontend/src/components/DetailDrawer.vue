<template>
  <el-drawer
    :model-value="modelValue"
    :title="title"
    :size="width"
    destroy-on-close
    @update:model-value="v => $emit('update:modelValue', v)"
    @closed="$emit('closed')"
  >
    <div v-loading="loading" class="detail-drawer-body">
      <slot />
    </div>
    <template v-if="$slots.footer" #footer>
      <div class="detail-drawer-footer"><slot name="footer" /></div>
    </template>
  </el-drawer>
</template>

<script setup>
/**
 * 详情抽屉骨架（2026-07-03 治理 F-6）。
 * 只封装抽屉外壳（标题/宽度/loading/底部操作区），内容完全自由——
 * 参照已成功的 components/design/RequestDetailDrawer.vue 泛化。新页面统一用它。
 */
defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '详情' },
  width: { type: [String, Number], default: 640 },
  loading: { type: Boolean, default: false },
})
defineEmits(['update:modelValue', 'closed'])
</script>

<style scoped>
.detail-drawer-body { min-height: 120px; }
.detail-drawer-footer { display: flex; justify-content: flex-end; gap: 10px; }
</style>
