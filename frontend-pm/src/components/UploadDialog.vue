<template>
  <UiModal :model-value="modelValue" title="上传新版本" @update:model-value="onModalToggle">
    <div class="up-form">
      <label
        class="up-drop"
        :class="{ has: file, dragging }"
        for="up-file-input"
        @dragenter.prevent="onDragOver"
        @dragover.prevent="onDragOver"
        @dragleave="onDragLeave"
        @drop.prevent="onDrop"
      >
        <input id="up-file-input" type="file" class="up-input" :disabled="busy" @change="onPick" />
        <span class="up-icon" aria-hidden="true">↥</span>
        <span v-if="!file">点击选择或拖入文件（单文件 ≤ {{ maxMb }}MB）</span>
        <span v-else class="up-name">{{ file.name }} <em class="num">{{ fmtSize(file.size) }}</em></span>
      </label>
      <p v-if="oversize" class="up-error">超过 {{ maxMb }}MB 上限——大文件请改用「外部链接」类型备注网盘地址</p>
      <p v-else-if="dropError" class="up-error">{{ dropError }}</p>
      <div class="form-item">
        <label class="field-label">修改说明（选填，一句话）</label>
        <input v-model.trim="note" class="input" type="text" placeholder="如：按顾问反馈补充了样品价" maxlength="200" />
      </div>
      <p class="up-hint">版本号自动 +1，AI 将自动对比上一版生成差异概要。</p>
    </div>
    <template #footer></template>
    <div class="up-foot">
      <button class="btn" type="button" :disabled="busy" @click="onModalToggle(false)">取消</button>
      <button class="btn btn-accent" type="button" :disabled="!file || oversize || busy" @click="submit">
        <span v-if="busy" class="spinner"></span>{{ busy ? '上传中…' : '上传' }}
      </button>
    </div>
  </UiModal>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import UiModal from './UiModal.vue'
import { fmtSize } from '../utils/labels.js'

const props = defineProps({
  modelValue: Boolean,
  maxMb: { type: Number, default: 50 },
  // @upload 以函数 prop 承接：emit() 拿不到监听器返回的 Promise，无法等上传完成再关窗
  onUpload: Function,
})
const emit = defineEmits(['update:modelValue'])

const file = ref(null)
const note = ref('')
const busy = ref(false)
const dragging = ref(false)
const dropError = ref('')

const oversize = computed(() => file.value && file.value.size > props.maxMb * 1024 * 1024)

watch(
  () => props.modelValue,
  (open) => {
    if (open) { file.value = null; note.value = ''; busy.value = false; dragging.value = false; dropError.value = '' }
    toggleWindowDropGuard(open)
  },
  { immediate: true }
)
onBeforeUnmount(() => toggleWindowDropGuard(false))

// 对话框打开期间拦掉浏览器对拖放的默认行为：文件拖偏落到框外时整页会被替换成该文件
function preventWindowDrop(e) { e.preventDefault() }
function toggleWindowDropGuard(on) {
  const fn = on ? 'addEventListener' : 'removeEventListener'
  window[fn]('dragover', preventWindowDrop)
  window[fn]('drop', preventWindowDrop)
}

function onDragOver(e) {
  if (busy.value) {
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'none' // 上传中给禁止光标，而不是收下再静默丢弃
    return
  }
  dragging.value = true
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'
}

function onDragLeave(e) {
  if (e.currentTarget.contains(e.relatedTarget)) return // 移入子元素不算离开
  dragging.value = false
}

function onDrop(e) {
  dragging.value = false
  if (busy.value) return
  // 文件夹拖进来是个不可读的伪 File，上传时才炸且报成"网络异常"，在门口拦掉
  if (e.dataTransfer?.items?.[0]?.webkitGetAsEntry?.()?.isDirectory) {
    dropError.value = '请拖入单个文件，不支持文件夹'
    return
  }
  const picked = e.dataTransfer?.files?.[0]
  if (picked) { file.value = picked; dropError.value = '' }
}

function onPick(e) {
  file.value = e.target.files?.[0] || null
  if (file.value) dropError.value = ''
}

function onModalToggle(open) {
  if (!open && busy.value) return // 上传中不许关窗：关了上传仍在后台跑，会复现"没反馈但传上了"
  emit('update:modelValue', open)
}

async function submit() {
  if (busy.value || !file.value) return
  busy.value = true
  try {
    await props.onUpload?.(file.value, note.value)
    emit('update:modelValue', false)
  } catch {
    // 失败留在窗内可改后重试；错误提示已由 api client 统一弹出
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
.up-drop.dragging { border-color: var(--ink); color: var(--ink); background: var(--paper-sunken); }
.up-drop.has { border-style: solid; border-color: var(--ink); color: var(--ink); }
.up-input { display: none; }
.up-icon { font-size: 16px; }
.up-name em { font-style: normal; color: var(--ink-3); margin-left: 6px; }
.up-error { font-size: 12px; color: var(--danger); }
.up-hint { font-size: 12px; color: var(--ink-4); }
.form-item { display: block; }
.up-foot { display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px; }
</style>
