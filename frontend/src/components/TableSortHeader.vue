<template>
  <button type="button" class="table-sort-header" :aria-label="`${label}，${nextAction}`" @click="$emit('sort')">
    <slot>{{ label }}</slot><span aria-hidden="true">{{ order === 'ascending' ? '↑' : order === 'descending' ? '↓' : '↕' }}</span>
  </button>
</template>
<script setup>
import { computed } from 'vue'
const props = defineProps({ label: String, order: String })
defineEmits(['sort'])
const nextAction = computed(() => props.order === 'ascending' ? '点击降序' : props.order === 'descending' ? '点击取消排序' : '点击升序')
</script>
<style scoped>
.table-sort-header { display: inline-flex; align-items: center; gap: 6px; padding: 4px 0; border: 0; background: transparent; color: inherit; font: inherit; text-align: inherit; cursor: pointer; }
.table-sort-header:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 3px; border-radius: 2px; }
</style>
