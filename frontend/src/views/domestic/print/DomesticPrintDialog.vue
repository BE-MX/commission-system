<template>
  <el-dialog
    :model-value="visible" :title="title" :width="isLabel ? '520px' : '900px'"
    top="5vh" destroy-on-close @update:model-value="close"
  >
    <div v-if="loadError" class="state-line">{{ loadError }}</div>
    <div v-else-if="loading" class="state-line">
      <el-icon class="is-loading"><Loading /></el-icon><span>加载打印内容…</span>
    </div>
    <!-- 预览用 iframe 装的是完整独立文档，打印时对它调 print()，
         所见即所印，也不会把订单页和侧边栏带进去 -->
    <iframe
      v-show="!loading && !loadError" ref="frameRef" class="preview-frame"
      :class="isLabel ? 'preview-frame--label' : 'preview-frame--card'"
      :srcdoc="docHtml" title="打印预览"
    />

    <template #footer>
      <div class="footer-bar">
        <div v-if="isLabel" class="copies">
          <span class="copies-label">份数</span>
          <el-input-number v-model="copies" :min="1" :max="50" size="small" />
        </div>
        <span v-if="mode === 'wxacode' && card && card.env_version !== 'release'" class="tip tip--warn">
          体验版码：只有小程序体验成员能扫开，别贴给客户看的单据
        </span>
        <span v-else class="tip">打印对话框里缩放选「实际大小 / 100%」{{ isLabel ? '，纸张设为 30 × 20mm' : '' }}</span>
        <div class="footer-actions">
          <GlassButton variant="ghost" @click="close">关闭</GlassButton>
          <GlassButton variant="primary" left-icon="Printer" :disabled="loading || !!loadError" @click="doPrint">
            打印
          </GlassButton>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
/**
 * 内贸打印弹框（流转卡 / 二维码标签 / 进度码标签共用）。
 * 弹框停留在订单页上，用户关掉就回到原来的列表和抽屉，不用按浏览器后退。
 */
import { computed, ref, watch } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import { fetchImageDataUrl, getItemWxacode, getPrintCard } from '@/api/domestic'
import GlassButton from '@/components/GlassButton.vue'
import logoUrl from '@/assets/domestic-logo.png'
import { buildCardDoc, buildLabelDoc, buildWxacodeLabelDoc } from './printDocs'

const props = defineProps({
  visible: { type: Boolean, default: false },
  mode: { type: String, default: 'card' },   // card=流转卡 / label=二维码标签 / wxacode=进度码标签
  itemId: { type: [Number, String], default: null },   // 三种模式都是明细级
})
const emit = defineEmits(['update:visible'])

const loading = ref(false)
const loadError = ref('')
const card = ref(null)
const copies = ref(1)
const frameRef = ref(null)

const isLabel = computed(() => props.mode !== 'card')
const title = computed(() => ({
  label: '二维码标签（30×20mm）',
  wxacode: '进度码标签（30×20mm）',
}[props.mode] || '工艺流转卡'))

const docHtml = computed(() => {
  if (!card.value) return ''
  if (props.mode === 'wxacode') {
    return buildWxacodeLabelDoc({
      image: card.value.image_base64,
      domesticNo: card.value.domestic_no,
      logoUrl,
      copies: copies.value,
    })
  }
  return props.mode === 'label'
    ? buildLabelDoc({ card: card.value, logoUrl, copies: copies.value })
    : buildCardDoc({ card: card.value, imageMap: imageMap.value })
})

const imageMap = ref({})

// LOGO 是 Vite 产出的绝对路径，srcdoc 里能直接用；参考图要鉴权，转 data URL 带进去
async function loadReferenceImages(item) {
  const paths = ['hairstyle_images', 'color_images', 'style_images', 'remark_images']
    .flatMap(key => item[key] || [])
  if (!paths.length) return {}
  const entries = await Promise.all(paths.map(async path => {
    try {
      return [path, await fetchImageDataUrl(path)]
    } catch {
      return [path, '']
    }
  }))
  return Object.fromEntries(entries.filter(([, url]) => url))
}

async function load() {
  loading.value = true
  loadError.value = ''
  card.value = null
  imageMap.value = {}
  copies.value = 1
  try {
    if (props.mode === 'wxacode') {
      const res = await getItemWxacode(props.itemId)
      card.value = res.data
    } else {
      const res = await getPrintCard(props.itemId)
      card.value = res.data
      if (props.mode === 'card') {
        imageMap.value = await loadReferenceImages(res.data.item || {})
      }
    }
  } catch {
    loadError.value = props.mode === 'wxacode'
      ? '进度码没生成出来，原因见右上角报错提示'
      : '这张卡对应的明细已经不存在了（订单可能已被删除）'
  } finally {
    loading.value = false
  }
}

function doPrint() {
  const frame = frameRef.value
  if (!frame?.contentWindow) return
  // 必须先 focus：不聚焦时部分浏览器会把打印指令派给父文档，又变成打印整页
  frame.contentWindow.focus()
  frame.contentWindow.print()
}

function close() {
  emit('update:visible', false)
}

watch(() => [props.visible, props.itemId, props.mode], ([isOpen]) => {
  if (isOpen && props.itemId) load()
}, { immediate: true })
</script>

<style scoped>
.state-line {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 60px 0;
  color: var(--el-text-color-secondary);
}

.preview-frame {
  width: 100%;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-light);
}

/* 标签放大 3 倍后约 90×60mm，留够竖向空间 */
.preview-frame--label { height: 320px; }
.preview-frame--card { height: 62vh; }

.footer-bar {
  display: flex;
  align-items: center;
  gap: 16px;
}

.copies {
  display: flex;
  align-items: center;
  gap: 8px;
}

.copies-label {
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.tip {
  flex: 1;
  text-align: left;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.tip--warn { color: var(--el-color-warning); }

.footer-actions {
  display: flex;
  gap: 8px;
}
</style>
