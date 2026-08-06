<template>
  <el-dialog
    :model-value="visible"
    title="参考图库"
    width="760px"
    append-to-body
    class="reference-library-dialog"
    @update:model-value="emit('update:visible', $event)"
    @open="onOpen"
  >
    <div class="lib-toolbar">
      <div class="lib-tabs" role="tablist">
        <button
          type="button"
          class="tab-chip"
          :class="{ 'is-active': scope === 'public' }"
          role="tab"
          :aria-selected="scope === 'public'"
          @click="switchScope('public')"
        >公库</button>
        <button
          type="button"
          class="tab-chip"
          :class="{ 'is-active': scope === 'private' }"
          role="tab"
          :aria-selected="scope === 'private'"
          @click="switchScope('private')"
        >私库</button>
      </div>
      <span class="lib-hint">{{ scope === 'public' ? '公库图片全员可用' : '私库图片仅自己可见可用' }}</span>
      <div v-if="canUpload" v-permission="'design_image:write'" class="lib-upload">
        <AppUpload
          :model-value="uploadModel"
          :upload-fn="doUpload"
          accept="image/jpeg,image/png,image/webp"
          :max-size-mb="maxUploadMb"
          :multiple="false"
          :show-list="false"
          button-text="上传图片"
          @update:model-value="uploadModel = []"
        >
          <GlassButton variant="outline" size="sm" :loading="uploading">
            <template #left-icon><el-icon><Upload /></el-icon></template>
            上传到{{ scope === 'public' ? '公库' : '私库' }}
          </GlassButton>
        </AppUpload>
      </div>
    </div>

    <div v-loading="loading" class="lib-grid">
      <div
        v-for="item in items"
        :key="item.id"
        class="lib-item"
        :class="{ 'is-active': selected?.id === item.id }"
        role="button"
        tabindex="0"
        @click="selected = item"
        @keydown.enter.prevent="selected = item"
      >
        <img v-if="thumbUrl(item.id)" :src="thumbUrl(item.id)" :alt="item.title || '参考图'" loading="lazy" />
        <span v-else class="lib-item-loading"><el-icon class="is-loading"><Loading /></el-icon></span>
        <span class="lib-item-title">{{ item.title || '未命名' }}</span>
        <button
          v-if="canDelete(item)"
          type="button"
          class="lib-item-delete"
          :aria-label="`删除 ${item.title || '图片'}`"
          @click.stop="remove(item)"
        ><el-icon><Delete /></el-icon></button>
      </div>
      <p v-if="!loading && !items.length" class="lib-empty">
        {{ scope === 'private' ? '私库还没有图片，点击右上角上传' : '公库还没有图片' }}
      </p>
    </div>

    <template #footer>
      <span class="lib-selected">{{ selected ? `已选：${selected.title || '未命名'}` : '选择一张图作为基准参考图' }}</span>
      <GlassButton variant="ghost" @click="close">取消</GlassButton>
      <GlassButton variant="primary" :disabled="!selected" @click="confirm">设为基准参考图</GlassButton>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Delete, Loading, Upload } from '@element-plus/icons-vue'
import AppUpload from '@/components/AppUpload.vue'
import GlassButton from '@/components/GlassButton.vue'
import { deleteLibraryAsset, listLibraryAssets, uploadLibraryAsset } from '@/api/designImage'
import { useAuthStore } from '@/stores/auth'
import { msgError, msgSuccess } from '@/utils/feedback'
import { useLibraryObjectUrls } from '../composables/useLibraryObjectUrls'

const props = defineProps({
  visible: { type: Boolean, default: false },
  maxUploadMb: { type: Number, default: 20 },
})
const emit = defineEmits(['update:visible', 'select'])

const auth = useAuthStore()
const libraryUrls = useLibraryObjectUrls()

const scope = ref('public')
const items = ref([])
const selected = ref(null)
const loading = ref(false)
const uploading = ref(false)
const uploadModel = ref([])

const isAdmin = computed(() => auth.hasPermission('design_image:admin'))
const canUpload = computed(() => scope.value === 'private' || isAdmin.value)

function thumbUrl(assetId) {
  return libraryUrls.get(assetId)
}

function canDelete(item) {
  return scope.value === 'private' || isAdmin.value
}

async function fetchItems() {
  loading.value = true
  selected.value = null
  try {
    const response = await listLibraryAssets(scope.value)
    items.value = response?.data?.items ?? []
    for (const item of items.value) {
      libraryUrls.load(item.id).catch(() => {})
    }
  } catch {
    msgError('参考图库读取失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

function switchScope(next) {
  if (scope.value === next) return
  scope.value = next
  libraryUrls.revokeAll()
  void fetchItems()
}

async function doUpload(file) {
  uploading.value = true
  try {
    const response = await uploadLibraryAsset(scope.value, file.name.replace(/\.[^.]+$/, ''), file)
    const row = response?.data
    if (row) {
      items.value = [row, ...items.value]
      libraryUrls.load(row.id).catch(() => {})
      msgSuccess('上传')
    }
    return row
  } catch (error) {
    msgError(error?.response?.status === 403 ? '公库图片仅管理员可以上传' : '上传失败，请重试')
    throw error
  } finally {
    uploading.value = false
  }
}

async function remove(item) {
  try {
    await deleteLibraryAsset(item.id)
    items.value = items.value.filter(candidate => candidate.id !== item.id)
    if (selected.value?.id === item.id) selected.value = null
    msgSuccess('删除')
  } catch {
    msgError('删除失败，请稍后重试')
  }
}

function onOpen() {
  void fetchItems()
}

function close() {
  emit('update:visible', false)
}

function confirm() {
  if (!selected.value) return
  emit('select', selected.value)
  close()
}
</script>

<style scoped>
.lib-toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.lib-tabs { display: inline-flex; padding: 3px; border-radius: 999px; background: var(--toolbar-bg); box-shadow: 0 0 0 1px var(--border-color) inset; }
.tab-chip {
  padding: 6px 18px; border: 0; border-radius: 999px; background: transparent;
  color: var(--text-secondary); cursor: pointer; font-size: 13px;
  transition: background-color 160ms cubic-bezier(0.23, 1, 0.32, 1), color 160ms cubic-bezier(0.23, 1, 0.32, 1),
    box-shadow 160ms cubic-bezier(0.23, 1, 0.32, 1);
}
.tab-chip.is-active {
  background: var(--card-bg); box-shadow: 0 1px 4px rgba(26, 24, 22, 0.12);
  color: var(--color-gold-muted); font-weight: 700;
}
.lib-hint { color: var(--text-muted); font-size: 11px; }
.lib-upload { margin-left: auto; }

.lib-grid {
  display: grid; min-height: 240px; max-height: 420px; overflow-y: auto;
  grid-template-columns: repeat(auto-fill, minmax(128px, 1fr)); gap: 10px; padding: 2px;
}
.lib-item {
  position: relative; overflow: hidden; border: 2px solid transparent; border-radius: var(--radius-lg, 12px);
  background: var(--toolbar-bg); cursor: pointer; aspect-ratio: 1;
  transition: border-color 160ms cubic-bezier(0.23, 1, 0.32, 1), box-shadow 160ms cubic-bezier(0.23, 1, 0.32, 1);
}
.lib-item img { display: block; width: 100%; height: 100%; object-fit: cover; }
.lib-item.is-active { border-color: var(--color-primary); box-shadow: 0 0 0 3px var(--color-primary-glow); }
.lib-item-loading { display: grid; height: 100%; place-items: center; color: var(--text-muted); }
.lib-item-title {
  position: absolute; right: 0; bottom: 0; left: 0; overflow: hidden; padding: 14px 8px 6px;
  background: linear-gradient(transparent, rgba(30, 27, 24, 0.62));
  color: var(--text-on-dark); font-size: 11px; text-overflow: ellipsis; white-space: nowrap;
}
.lib-item-delete {
  position: absolute; top: 6px; right: 6px; display: grid; width: 24px; height: 24px; place-items: center;
  border: 0; border-radius: 50%; background: rgba(30, 27, 24, 0.62); color: var(--text-on-dark);
  cursor: pointer; font-size: 12px; opacity: 0;
  transition: opacity 160ms cubic-bezier(0.23, 1, 0.32, 1), background-color 160ms cubic-bezier(0.23, 1, 0.32, 1);
}
.lib-item:focus-within .lib-item-delete, .lib-item.is-active .lib-item-delete { opacity: 1; }
.lib-empty { grid-column: 1 / -1; margin: 60px 0; color: var(--text-muted); font-size: 12px; text-align: center; }
.lib-selected { margin-right: auto; color: var(--text-muted); font-size: 12px; }

@media (hover: hover) and (pointer: fine) {
  .tab-chip:hover { color: var(--text-primary); }
  .lib-item:hover { box-shadow: var(--card-shadow-hover); }
  .lib-item:hover .lib-item-delete { opacity: 1; }
  .lib-item-delete:hover { background: var(--color-danger); }
}
@media (prefers-reduced-motion: reduce) {
  .tab-chip, .lib-item, .lib-item-delete { transition: none; }
}
</style>
