<template>
  <NodeViewWrapper as="figure" class="knowledge-image" :class="{ selected }" data-knowledge-image>
    <div v-if="isPending" class="image-placeholder" contenteditable="false">
      <el-progress
        v-if="node.attrs.uploadStatus !== 'error'"
        type="circle"
        :width="54"
        :stroke-width="4"
        :percentage="Number(node.attrs.uploadProgress || 0)"
        :indeterminate="!node.attrs.uploadProgress"
      />
      <span v-if="node.attrs.uploadStatus === 'error'" class="upload-error">上传失败</span>
      <small>{{ node.attrs.uploadError || '正在安全上传图片…' }}</small>
      <button v-if="editor.isEditable && node.attrs.uploadStatus === 'error'" type="button" @click="retry">重新选择图片</button>
      <button v-if="editor.isEditable" type="button" @click="deleteNode">移除</button>
    </div>
    <template v-else>
      <div class="image-frame" contenteditable="false">
        <img v-if="objectUrl" :src="objectUrl" :alt="node.attrs.alt || ''" />
        <span v-else-if="loadError" class="upload-error">图片暂时无法加载</span>
        <span v-else>加载图片…</span>
      </div>
      <div v-if="editor.isEditable" class="image-fields" contenteditable="false">
        <el-input
          :model-value="node.attrs.alt"
          maxlength="500"
          placeholder="图片替代文本（建议填写）"
          @update:model-value="updateAttributes({ alt: $event })"
        />
        <el-input
          :model-value="node.attrs.caption"
          maxlength="500"
          placeholder="图片说明（可选）"
          @update:model-value="updateAttributes({ caption: $event })"
        />
        <button type="button" @click="deleteNode">删除图片</button>
      </div>
      <figcaption v-else-if="node.attrs.caption">{{ node.attrs.caption }}</figcaption>
    </template>
  </NodeViewWrapper>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { nodeViewProps, NodeViewWrapper } from '@tiptap/vue-3'
import { getKnowledgeImageBlob } from '@/api/knowledge'

const props = defineProps(nodeViewProps)
const objectUrl = ref('')
const loadError = ref(false)
const isPending = computed(() => !Number.isInteger(props.node.attrs.assetId))

function releaseUrl() {
  if (objectUrl.value) URL.revokeObjectURL(objectUrl.value)
  objectUrl.value = ''
}

function retry() {
  deleteNode()
  props.editor.view.dom.dispatchEvent(new CustomEvent('knowledge-image-retry', { bubbles: true }))
}

async function load() {
  releaseUrl()
  loadError.value = false
  if (isPending.value) return
  const expected = props.node.attrs.assetId
  try {
    const response = await getKnowledgeImageBlob(expected)
    if (props.node.attrs.assetId !== expected) return
    const nextUrl = URL.createObjectURL(response.data)
    if (props.node.attrs.assetId !== expected) {
      URL.revokeObjectURL(nextUrl)
      return
    }
    objectUrl.value = nextUrl
  } catch {
    loadError.value = true
  }
}

watch(() => props.node.attrs.assetId, load, { immediate: true })
onBeforeUnmount(releaseUrl)
</script>

<style scoped>
.knowledge-image { margin: 18px 0; padding: 8px; border: 1px solid transparent; border-radius: 10px; }
.knowledge-image.selected { border-color: var(--color-primary); background: var(--color-primary-light); }
.image-frame { display: grid; min-height: 120px; place-items: center; color: var(--text-muted-blue); background: var(--surface-subtle); }
.image-frame img { display: block; max-width: 100%; max-height: 640px; object-fit: contain; }
.image-placeholder { display: grid; min-height: 160px; place-items: center; gap: 8px; border: 1px dashed var(--border-color); border-radius: 9px; color: var(--text-secondary); background: var(--surface-subtle); }
.image-placeholder small { color: var(--text-muted-blue); }
.image-fields { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto; gap: 8px; margin-top: 8px; }
button { padding: 6px 10px; border: 0; border-radius: 7px; color: var(--color-danger); background: transparent; cursor: pointer; }
figcaption { margin-top: 6px; color: var(--text-muted-blue); text-align: center; font-size: 13px; }
.upload-error { color: var(--color-danger); font-weight: 700; }
@media (max-width: 900px) { .image-fields { grid-template-columns: 1fr; } }
</style>
