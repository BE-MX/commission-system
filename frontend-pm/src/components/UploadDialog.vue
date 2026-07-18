<template>
  <UiModal :model-value="modelValue" title="上传新版本" @update:model-value="emit('update:modelValue', $event)">
    <div class="up-form">
      <label class="up-drop" :class="{ has: file }" for="up-file-input">
        <input id="up-file-input" type="file" class="up-input" @change="onPick" />
        <span class="up-icon" aria-hidden="true">↥</span>
        <span v-if="!file">选择文件（单文件 ≤ {{ maxMb }}MB）</span>
        <span v-else class="up-name">{{ file.name }} <em class="num">{{ fmtSize(file.size) }}</em></span>
      </label>
      <p v-if="oversize" class="up-error">超过 {{ maxMb }}MB 上限——大文件请改用「外部链接」类型备注网盘地址</p>
      <div class="form-item">
        <label class="field-label">修改说明（选填，一句话）</label>
        <input v-model.trim="note" class="input" type="text" placeholder="如：按顾问反馈补充了样品价" maxlength="200" />
      </div>
      <p class="up-hint">版本号自动 +1，AI 将自动对比上一版生成差异概要。</p>
    </div>
    <template #footer></template>
    <div class="up-foot">
      <button class="btn" type="button" @click="emit('update:modelValue', false)">取消</button>
      <button class="btn btn-accent" type="button" :disabled="!file || oversize || busy" @click="submit">
        <span v-if="busy" class="spinner"></span>上传
      </button>
    </div>
  </UiModal>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import UiModal from './UiModal.vue'
import { fmtSize } from '../utils/labels.js'

const props = defineProps({
  modelValue: Boolean,
  maxMb: { type: Number, default: 50 },
})
const emit = defineEmits(['update:modelValue', 'upload'])

const file = ref(null)
const note = ref('')
const busy = ref(false)

const oversize = computed(() => file.value && file.value.size > props.maxMb * 1024 * 1024)

watch(
  () => props.modelValue,
  (open) => {
    if (open) { file.value = null; note.value = ''; busy.value = false }
  }
)

function onPick(e) {
  file.value = e.target.files?.[0] || null
}

async function submit() {
  if (busy.value) return
  busy.value = true
  try {
    await emit('upload', file.value, note.value)
    emit('update:modelValue', false)
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.up-form { display: flex; flex-direction: column; gap: 14px; }
.up-drop {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 1px dashed var(--hairline-strong);
  border-radius: var(--radius);
  padding: 26px 16px;
  color: var(--ink-3);
  font-size: 13px;
  cursor: pointer;
  transition: border-color var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out);
}
@media (hover: hover) and (pointer: fine) {
  .up-drop:hover { border-color: var(--ink-3); color: var(--ink); background: var(--paper-sunken); }
}
.up-drop.has { border-style: solid; border-color: var(--ink); color: var(--ink); }
.up-input { display: none; }
.up-icon { font-size: 16px; }
.up-name em { font-style: normal; color: var(--ink-3); margin-left: 6px; }
.up-error { font-size: 12px; color: var(--danger); }
.up-hint { font-size: 12px; color: var(--ink-4); }
.form-item { display: block; }
.up-foot { display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px; }
</style>
