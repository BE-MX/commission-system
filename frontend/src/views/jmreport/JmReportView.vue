<template>
  <div class="report-container">
    <div v-if="state.loading" class="report-loading">
      <el-skeleton :rows="10" animated />
      <p class="loading-text">正在加载报表设计器...</p>
    </div>

    <div v-else-if="state.error" class="report-error">
      <el-result icon="error" title="报表服务不可用" :sub-title="state.error">
        <template #extra>
          <el-button type="primary" @click="initReport">重新加载</el-button>
        </template>
      </el-result>
    </div>

    <iframe
      v-else-if="iframeUrl"
      :src="iframeUrl"
      class="report-iframe"
      frameborder="0"
      allowfullscreen
      @load="onIframeLoad"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useJmReportStore } from '@/stores/jmreport'

const props = defineProps({
  reportCode: { type: String, default: null },
  mode: {
    type: String,
    default: 'design',
    validator: (v) => ['view', 'design'].includes(v),
  },
})

const route = useRoute()
const reportStore = useJmReportStore()

const state = ref({ loading: true, error: null })

const reportCode = computed(
  () => props.reportCode || route.query.reportCode || null,
)

const iframeUrl = computed(() => {
  if (!reportStore.token) return ''
  if (reportCode.value && props.mode === 'view') {
    return reportStore.getReportUrl(reportCode.value)
  }
  return reportStore.designerUrl
})

async function initReport() {
  state.value.loading = true
  state.value.error = null
  try {
    await reportStore.fetchToken()
  } catch (err) {
    state.value.error = err?.message || '无法连接到报表服务，请稍后重试'
  } finally {
    state.value.loading = false
  }
}

function onIframeLoad() {
  // 留个钩子方便后续埋点 / 性能监测
}

onMounted(initReport)
</script>

<style scoped>
.report-container {
  width: 100%;
  height: 100%;
  min-height: calc(100vh - 120px);
  display: flex;
  flex-direction: column;
  background: #f5f7fa;
}
.report-iframe {
  width: 100%;
  flex: 1;
  min-height: calc(100vh - 120px);
  border: none;
  background: #fff;
}
.report-loading {
  padding: 40px;
  text-align: center;
}
.loading-text {
  margin-top: 16px;
  color: #909399;
  font-size: 14px;
}
.report-error {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 400px;
}
</style>
