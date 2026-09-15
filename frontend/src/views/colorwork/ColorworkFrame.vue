<template>
  <div class="colorwork-page">
    <div v-if="error" class="colorwork-state" role="alert">
      <el-icon><WarningFilled /></el-icon>
      <p>{{ error }}</p>
      <el-button @click="load">重试</el-button>
    </div>
    <div v-if="loading" class="colorwork-state">
      <el-icon class="is-loading"><Loading /></el-icon>
      <p>正在进入{{ viewLabel }}…</p>
    </div>
    <iframe
      v-if="frameUrl"
      :src="frameUrl"
      class="colorwork-frame"
      :title="`库存色块图工作台 - ${viewLabel}`"
      @load="loading = false"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Loading, WarningFilled } from '@element-plus/icons-vue'
import { getColorworkSsoLink } from '@/api/colorwork'

// 路由 name → 工作台视图（?view= 参数），与后端 VIEW_PERMISSIONS 一致
const ROUTE_VIEWS = {
  ColorworkDownload: { view: 'library', label: '库存图直接下载' },
  ColorworkEdit: { view: 'inventory', label: '实时库存图修改' },
  ColorworkMaster: { view: 'master', label: '原始库存图文件' },
}

const route = useRoute()
const current = computed(() => ROUTE_VIEWS[route.name] || ROUTE_VIEWS.ColorworkDownload)
const viewLabel = computed(() => current.value.label)

const loading = ref(true)
const error = ref('')
const frameUrl = ref('')
let loadSeq = 0

async function load() {
  const seq = ++loadSeq
  loading.value = true
  error.value = ''
  frameUrl.value = ''
  try {
    const data = await getColorworkSsoLink(current.value.view)
    if (seq !== loadSeq) return // 已切到其他视图，丢弃过期响应
    frameUrl.value = data.url
  } catch (reason) {
    if (seq !== loadSeq) return
    loading.value = false
    error.value = reason?.response?.data?.detail || '进入工作台失败，请稍后重试或联系管理员确认页面权限。'
  }
}

onMounted(load)
// 三个页面共用本组件：路由切换时按新视图重新换取 SSO 链接
watch(() => route.name, (next, prev) => { if (next !== prev) load() })
</script>

<style scoped>
/* 顶掉 MainLayout 内容区内边距，让子站点占满可用区域（头 56px + 页签约 44px） */
.colorwork-page {
  position: relative;
  margin: -24px -28px;
  height: calc(100dvh - var(--header-height, 56px) - 44px);
  min-height: 480px;
  background: var(--page-bg);
}
.colorwork-frame {
  display: block;
  width: 100%;
  height: 100%;
  border: 0;
}
.colorwork-state {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--text-secondary);
  font-size: 14px;
}
.colorwork-state .el-icon { font-size: 26px; }
@media (max-width: 640px) {
  .colorwork-page { margin: -12px -10px; }
}
</style>
