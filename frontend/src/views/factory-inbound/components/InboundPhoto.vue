<template>
  <div class="photo">
    <button v-if="thumb" class="photo-trigger" type="button" @click="open = true" aria-label="放大查看单据照片">
      <img :src="thumb" alt="" /><span>查看原单</span>
    </button>
    <GlassButton v-else-if="failed" variant="link" @click="load">重新加载照片</GlassButton>
    <span v-else class="photo-state">加载照片…</span>
    <el-dialog v-model="open" title="单据照片" width="760px" append-to-body>
      <div v-if="note.has_original" class="photo-options">
        <GlassButton :variant="original ? 'ghost' : 'primary'" @click="original = false">校正图</GlassButton>
        <GlassButton :variant="original ? 'primary' : 'ghost'" @click="original = true">原图</GlassButton>
      </div>
      <img v-if="shown" class="photo-full" :src="shown" :alt="original ? '工厂发货单原图' : '校正后的工厂发货单'" />
      <GlassButton v-else-if="failed" @click="load">重新加载照片</GlassButton>
      <p v-else role="status">加载照片…</p>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import { factoryInboundApi } from '@/api/factoryInbound'

const props = defineProps({ note: { type: Object, required: true } })
const thumb = ref('')
const source = ref('')
const open = ref(false)
const original = ref(false)
const failed = ref(false)
const shown = computed(() => original.value ? source.value : thumb.value)
let active

async function load() {
  active?.abort()
  const controller = new AbortController()
  active = controller
  failed.value = false
  const useOriginal = open.value && original.value
  const destination = useOriginal ? source : thumb
  if (destination.value) return
  try {
    const result = await factoryInboundApi.image(props.note.id, useOriginal, controller.signal)
    if (!controller.signal.aborted) destination.value = URL.createObjectURL(result.data)
  } catch {
    if (!controller.signal.aborted) failed.value = true
  }
}

function clear() {
  active?.abort()
  for (const url of [thumb, source]) {
    if (url.value) URL.revokeObjectURL(url.value)
    url.value = ''
  }
}

watch(() => props.note.id, () => {
  clear()
  original.value = false
  open.value = false
  load()
}, { immediate: true })
watch(original, load)
onBeforeUnmount(clear)
</script>

<style scoped>
.photo-trigger {
  border: 0;
  background: none;
  color: var(--button-primary-link);
  cursor: pointer;
  font: inherit;
  padding: 0;
  display: grid;
  gap: 4px;
}
.photo-trigger img {
  width: 88px;
  height: 64px;
  object-fit: cover;
  object-position: top right;
  border-radius: 8px;
  border: 1px solid var(--el-border-color);
}
.photo-options { display: flex; gap: 8px; margin-bottom: 12px; }
.photo-full { display: block; width: 100%; height: auto; }
.photo-state { color: var(--el-text-color-secondary); }
</style>
