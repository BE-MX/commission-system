<script setup>
// 门户商品筛选：颜色/长度/克重输入 + 等级/颜色类型下拉；下拉选项由后端 facets 给出
defineProps({ filters: { type: Object, required: true }, facets: { type: Object, default: () => ({}) }, disabled: Boolean })
defineEmits(['submit'])
</script>

<template>
  <div class="portal-product-filters">
    <el-input v-model="filters.color" :disabled="disabled" aria-label="颜色" placeholder="颜色" maxlength="64" clearable @keyup.enter="$emit('submit')" />
    <el-input v-model="filters.length" :disabled="disabled" aria-label="长度" placeholder="长度" maxlength="32" clearable @keyup.enter="$emit('submit')" />
    <el-input v-model="filters.weight" :disabled="disabled" aria-label="克重" placeholder="克重" maxlength="32" clearable @keyup.enter="$emit('submit')" />
    <el-select v-model="filters.grade" :disabled="disabled" aria-label="等级" placeholder="等级" clearable value-on-clear=""><el-option v-for="grade in facets.grades || []" :key="grade" :label="grade" :value="grade" /></el-select>
    <el-select v-model="filters.color_type" :disabled="disabled" aria-label="颜色类型" placeholder="颜色类型" clearable value-on-clear=""><el-option v-for="type in facets.color_types || []" :key="type" :label="type" :value="type" /></el-select>
  </div>
</template>

<style scoped>
.portal-product-filters { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; }
@media (max-width: 640px) { .portal-product-filters { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>

<style>
/* 与共享筛选栏同法：Element Plus 下拉框内部最小 32px，统一到组件高度 */
.portal-product-filters .el-input__wrapper, .portal-product-filters .el-select__wrapper { box-sizing: border-box; min-height: var(--el-component-size); height: var(--el-component-size); }
</style>
