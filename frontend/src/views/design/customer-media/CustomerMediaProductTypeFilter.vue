<template>
  <div class="product-type-filter">
    <strong>Product type</strong>
    <div class="filter-values" role="group" aria-label="按Product type筛选">
      <button type="button" :aria-pressed="!active.length" :class="{ active: !active.length }" @click="emit('update:modelValue', [])">全部</button>
      <button v-for="type in options" :key="type.id" type="button" :aria-pressed="active.includes(type.id)" :class="{ active: active.includes(type.id) }" @click="toggle(type.id)">{{ type.value }}</button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  options: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue'])
const active = computed(() => props.modelValue.filter(id => props.options.some(type => type.id === id)))
function toggle(id) {
  emit('update:modelValue', active.value.includes(id)
    ? active.value.filter(value => value !== id) : [...active.value, id])
}
</script>

<style scoped>
.product-type-filter { display: flex; align-items: flex-start; gap: 12px; margin: 0 0 16px; }
.product-type-filter strong { min-width: 90px; padding-top: 5px; color: var(--text-secondary); font-size: 12px; }
.filter-values { display: flex; flex-wrap: wrap; gap: 7px; }
.filter-values button { padding: 5px 10px; border: 1px solid var(--border-color); border-radius: 999px; color: var(--text-secondary); background: var(--card-bg); cursor: pointer; }
.filter-values button.active { border-color: var(--color-primary); color: var(--color-primary-hover); background: var(--color-primary-light); }
</style>
