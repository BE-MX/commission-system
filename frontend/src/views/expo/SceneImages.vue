<template>
  <div class="scene-img-page">
    <div class="page-hint">
      上传各生成场景的示意图 —— 仅供试戴「甄选发型」页滑动选择时示意，<b>不参与合成</b>。
      建议竖版 3:4，支持 jpg / png / webp，上传后自动降采样控体积。未上传的场景在甄选页显示占位卡。
    </div>

    <div v-loading="loading">
      <div v-for="cat in groupedScenes" :key="cat.key" class="cat-block">
        <div class="cat-title">{{ cat.label }}<small>{{ cat.scenes.length }} 景 · 已上传 {{ cat.doneCount }}</small></div>
        <div class="scene-grid">
          <div v-for="s in cat.scenes" :key="s.key" class="scene-card">
            <div class="thumb">
              <el-image
                v-if="s.image" :src="s.image" :preview-src-list="[s.image]"
                preview-teleported fit="cover" class="thumb-img"
              />
              <div v-else class="thumb-ph">
                <span class="ph-emoji">{{ emoji(s.key) }}</span>
                <span class="ph-txt">未上传</span>
              </div>
            </div>
            <div class="meta">
              <div class="lb">{{ s.label }}</div>
              <div class="tg">{{ s.tagline }}</div>
            </div>
            <div class="ops" v-permission="'expo:admin'">
              <el-upload
                :show-file-list="false" accept="image/jpeg,image/png,image/webp"
                :http-request="(o) => doUpload(s, o)"
              >
                <GlassButton variant="link" left-icon="Upload">{{ s.image ? '替换' : '上传' }}</GlassButton>
              </el-upload>
              <GlassButton
                v-if="s.image" variant="link" link-tone="danger" left-icon="Delete"
                @click="doDelete(s)"
              >删除</GlassButton>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getScenes, uploadSceneImage, deleteSceneImage } from '@/api/expo'
import { confirmDanger, msgSuccess } from '@/utils/feedback'

const CAT_LABELS = { career: '职场专业', life: '长辈生活' }
const EMOJI = {
  whitecollar: '💼', teacher: '📚', shopowner: '🛍️', civilservant: '🏛️', doctor: '🩺',
  home: '🛋️', gathering: '🥂', lawyer: '⚖️', banker: '🏦', accountant: '📊', director: '📋',
  pharmacist: '💊', propertymanager: '🔑', hsrtravel: '🚄', weddinghost: '💐',
  schoolpickup: '🎒', squaredance: '💃', seniorcollege: '🎻', seniorcafe: '☕', parkwalk: '🌳',
}
function emoji(key) { return EMOJI[key] || '✦' }

const scenes = ref([])
const loading = ref(false)

const groupedScenes = computed(() => {
  const order = []
  const map = {}
  for (const s of scenes.value) {
    const c = s.category || 'career'
    if (!map[c]) { map[c] = []; order.push(c) }
    map[c].push(s)
  }
  return order.map((c) => ({
    key: c,
    label: CAT_LABELS[c] || c,
    scenes: map[c],
    doneCount: map[c].filter((s) => s.image).length,
  }))
})

async function fetchScenes() {
  loading.value = true
  try {
    const res = await getScenes({ mode: 'tryon' })
    scenes.value = res.data || []
  } finally {
    loading.value = false
  }
}

async function doUpload(scene, { file }) {
  try {
    const res = await uploadSceneImage(scene.key, file)
    // 同扩展名替换时 URL 不变，加时间戳强制刷新缓存
    scene.image = `${res.data.url}?t=${Date.now()}`
    ElMessage.success(`「${scene.label}」示意图已更新`)
  } catch { /* 拦截器已提示 */ }
}

async function doDelete(scene) {
  try {
    await confirmDanger('删除', `「${scene.label}」示意图`, '删除后甄选页该场景恢复占位卡。')
  } catch { return }
  try {
    await deleteSceneImage(scene.key)
    scene.image = null
    msgSuccess('删除')
  } catch { /* 拦截器已提示 */ }
}

onMounted(fetchScenes)
</script>

<style scoped>
.scene-img-page { padding-bottom: 24px; }
.page-hint {
  margin-bottom: 18px; padding: 12px 16px; border-radius: 10px;
  background: var(--toolbar-bg); border: 1px solid var(--border-color);
  color: var(--text-muted); font-size: 13px; line-height: 1.7;
}
.page-hint b { color: var(--color-primary); }
.cat-block { margin-bottom: 26px; }
.cat-title {
  font-size: 14px; font-weight: 600; margin-bottom: 12px;
  display: flex; align-items: baseline; gap: 10px;
}
.cat-title small { font-size: 12px; font-weight: 400; color: var(--text-muted); }
.scene-grid {
  display: grid; gap: 14px;
  grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
}
.scene-card {
  border: 1px solid var(--border-color); border-radius: 12px; overflow: hidden;
  background: var(--toolbar-bg); display: flex; flex-direction: column;
}
.thumb { width: 100%; aspect-ratio: 3 / 4; background: var(--toolbar-bg); }
.thumb-img { width: 100%; height: 100%; display: block; }
.thumb-ph {
  width: 100%; height: 100%; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 8px;
  color: var(--text-muted); border-bottom: 1px dashed var(--border-color);
}
.ph-emoji { font-size: 34px; opacity: 0.5; }
.ph-txt { font-size: 12px; }
.meta { padding: 10px 12px 4px; }
.meta .lb { font-size: 14px; font-weight: 600; }
.meta .tg { font-size: 11px; color: var(--text-muted); margin-top: 2px; letter-spacing: 0.08em; }
.ops { display: flex; gap: 4px; padding: 4px 8px 10px; align-items: center; }
</style>
