<template>
  <div class="draft-field">
    <el-form-item :label="label">
      <div class="field-row">
        <div class="ai-output">
          <span class="ai-badge">AI</span>
          <el-input
            v-if="type === 'textarea'"
            v-model="modelValue"
            type="textarea"
            :rows="rows"
            class="ai-input"
          />
          <el-input
            v-else
            v-model="modelValue"
            class="ai-input"
          />
        </div>
      </div>
      <div class="correction-row">
        <span class="corr-label">评价修正:</span>
        <el-input
          v-model="correctionValue"
          type="textarea"
          :rows="1"
          placeholder="此处录入需要补充和改动的部分..."
          class="corr-input"
        />
      </div>
    </el-form-item>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  label: { type: String, required: true },
  modelValue: { type: [String, Number], default: '' },
  correction: { type: String, default: '' },
  type: { type: String, default: 'text' },
  rows: { type: Number, default: 2 },
})

const emit = defineEmits(['update:modelValue', 'update:correction'])

const modelValue = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

const correctionValue = computed({
  get: () => props.correction,
  set: (val) => emit('update:correction', val),
})
</script>

<style scoped>
.draft-field { margin-bottom: 8px; }
.field-row { display: flex; align-items: flex-start; gap: 8px; }
.ai-output { flex: 1; display: flex; align-items: flex-start; gap: 6px; }
.ai-badge {
  font-size: 10px;
  font-weight: 700;
  color: #2563eb;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  padding: 2px 6px;
  border-radius: 4px;
  flex-shrink: 0;
  margin-top: 6px;
}
.ai-input :deep(.el-input__wrapper),
.ai-input :deep(.el-textarea__inner) {
  background: #f8fafc;
  border-color: #e2e8f0;
}
.correction-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-top: 4px;
  padding-left: 28px;
}
.corr-label {
  font-size: 11px;
  color: var(--text-tertiary, #8b95a5);
  flex-shrink: 0;
  margin-top: 6px;
}
.corr-input :deep(.el-textarea__inner) {
  background: #fefce8;
  border-color: #fde047;
  font-size: 12px;
}
.corr-input :deep(.el-textarea__inner::placeholder) {
  color: #a1a1aa;
}
</style>
