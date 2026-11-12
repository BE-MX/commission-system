<template>
  <div class="stats-seg" role="group" :aria-label="label">
    <button v-for="option in options" :key="option.value" type="button" :aria-pressed="modelValue === option.value"
            @click="$emit('update:modelValue', option.value); $emit('change', option.value)">{{ option.label }}</button>
  </div>
</template>
<script setup>
defineProps({ modelValue: [String, Number], options: { type: Array, required: true }, label: { type: String, default: '切换选项' } })
defineEmits(['update:modelValue', 'change'])
</script>
