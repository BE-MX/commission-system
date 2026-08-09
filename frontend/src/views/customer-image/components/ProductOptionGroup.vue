<script setup>
defineProps({
  option: { type: Object, required: true },
  modelValue: { type: [String, Boolean, Number], default: undefined },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue'])
</script>

<template>
  <fieldset class="option-group">
    <legend>
      {{ option.label }}
      <span v-if="option.required" class="required">必选</span>
    </legend>

    <el-switch
      v-if="option.control_type === 'boolean'"
      :model-value="Boolean(modelValue)"
      size="large"
      inline-prompt
      active-text="是"
      inactive-text="否"
      :disabled="disabled"
      @update:model-value="emit('update:modelValue', $event)"
    />

    <div
      v-else-if="['single_choice', 'color'].includes(option.control_type)"
      class="choice-grid"
      :class="{ colors: option.control_type === 'color' }"
    >
      <button
        v-for="value in option.values || []"
        :key="value.value"
        type="button"
        class="choice"
        :class="{ selected: modelValue === value.value }"
        :aria-pressed="modelValue === value.value"
        :disabled="disabled"
        @click="emit('update:modelValue', value.value)"
      >
        <span
          v-if="option.control_type === 'color'"
          class="swatch"
          :style="{ backgroundColor: value.color_hex || 'transparent' }"
        />
        <span>
          {{ value.label }}
          <small v-if="value.pantone_code">{{ value.pantone_code }}</small>
        </span>
      </button>
    </div>
  </fieldset>
</template>

<style scoped>
.option-group { display: grid; gap: 10px; margin: 0; padding: 0; border: 0; }
legend { margin-bottom: 10px; color: var(--cip-ink); font-size: 14px; font-weight: 650; }
.required { margin-left: 6px; color: var(--cip-danger); font-size: 11px; font-weight: 500; }
.choice-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.choice { display: flex; min-height: 44px; align-items: center; gap: 9px; padding: 8px 10px; cursor: pointer; border: 1px solid var(--cip-border); border-radius: 10px; color: var(--cip-ink); background: var(--cip-surface); text-align: left; transition: transform 180ms cubic-bezier(0.23, 1, 0.32, 1); }
.choice.selected { border-color: var(--cip-accent); background: var(--cip-accent-soft); }
.choice:active { transform: scale(.98); }
.choice small { display: block; margin-top: 2px; color: var(--cip-muted); font-size: 10px; }
.swatch { width: 22px; height: 22px; flex: 0 0 22px; border: 1px solid var(--cip-border); border-radius: 50%; box-shadow: inset 0 0 0 2px var(--cip-surface); }
@media (hover: hover) and (pointer: fine) { .choice:hover { border-color: var(--cip-accent); } }
@media (prefers-reduced-motion: reduce) { .choice { transition: none; } .choice:active { transform: none; } }
</style>
