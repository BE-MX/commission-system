<template>
  <div>
    <component :is="row.clickable ? 'button' : 'div'" v-for="row in rows" :key="row.key || row.label" type="button"
               class="stats-hb" :title="row.tooltip" @click="row.clickable && $emit('select', row)">
      <span>{{ row.label }}</span>
      <span class="stats-hb__track">
        <span class="stats-hb__fill" :class="row.tone ? `stats-hb__fill--${row.tone}` : ''"
              :style="{ width: `${Math.max(2, Math.min(100, Number(row.value || 0) / (row.max || 1) * 100))}%` }" />
        <span v-if="row.tick !== null && row.tick !== undefined" class="stats-hb__tick"
              :style="{ left: `${Math.min(100, Number(row.tick) / (row.max || 1) * 100)}%` }" />
      </span>
      <span class="stats-hb__value">{{ row.text }}</span>
    </component>
  </div>
</template>
<script setup>
defineProps({ rows: { type: Array, default: () => [] } })
defineEmits(['select'])
</script>
