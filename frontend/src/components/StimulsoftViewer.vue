<template>
  <div class="stimulsoft-viewer-wrap">
    <!-- 加载中 -->
    <div v-if="loading" class="viewer-loading">
      <el-skeleton :rows="8" animated />
      <p style="text-align: center; color: #909399; margin-top: 16px;">正在加载报表引擎...</p>
    </div>

    <!-- 错误 -->
    <div v-else-if="errorMsg" class="viewer-error">
      <el-result icon="error" title="报表加载失败" :sub-title="errorMsg">
        <template #extra>
          <el-button type="primary" @click="loadReport">重新加载</el-button>
        </template>
      </el-result>
    </div>

    <!-- 报表容器 -->
    <div
      v-show="!loading && !errorMsg"
      ref="viewerContainer"
      :style="{ height }"
    />
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { useStimulsoft } from '@/composables/useStimulsoft'
import { getReportTemplate, getReportData } from '@/api/reportCenter'

const props = defineProps({
  /** 报表编码，如 production_order_print */
  reportCode: { type: String, required: true },
  /** 查询参数，如 { order_no: 'PO20260601-001' } */
  params: { type: Object, default: () => ({}) },
  /** 容器高度 */
  height: { type: String, default: '75vh' },
})

const loading = ref(true)
const errorMsg = ref(null)
const viewerContainer = ref(null)

const { createViewer, ready: stimulsoftReady, ensureLoaded } = useStimulsoft()
let viewerInstance = null

async function loadReport() {
  if (!props.reportCode) return

  loading.value = true
  errorMsg.value = null

  try {
    console.log('[StimulsoftViewer] loadReport called, reportCode:', props.reportCode, 'params:', JSON.parse(JSON.stringify(props.params)))
    // 并行：等 Stimulsoft 引擎加载 + 请求模板和数据
    const [, templateRes, dataRes] = await Promise.all([
      ensureLoaded(),
      getReportTemplate(props.reportCode),
      getReportData(props.reportCode, props.params),
    ])

    // 解包响应（拦截器已解包 response.data，直接拿到 { code, data } 结构）
    const template = templateRes?.data ?? templateRes
    const reportData = dataRes?.data ?? dataRes
    console.log('[StimulsoftViewer] reportData items count:', reportData?.items?.length, 'item ids:', reportData?.items?.map(i => i.id))

    if (!template?.template_content) {
      throw new Error('模板内容为空')
    }

    const Stimulsoft = window.Stimulsoft

    // 创建报表实例
    const report = new Stimulsoft.Report.StiReport()
    report.load(template.template_content)

    // 清除数据库连接（确保只使用 JSON 数据）
    report.dictionary.databases.clear()

    // 注册 JSON 数据
    const dataSet = new Stimulsoft.System.Data.DataSet('data')
    dataSet.readJson(JSON.stringify(reportData))
    report.regData('data', 'data', dataSet)
    report.dictionary.synchronize()

    // 创建 Viewer
    if (viewerContainer.value) {
      viewerInstance = await createViewer(viewerContainer.value, report)
    }

    // 延迟关闭 loading：report 赋值后内部是 setTimeout + renderAsync2
    // 等两帧确保 DOM 更新
    await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))
    loading.value = false
  } catch (e) {
    console.error('报表加载失败:', e)
    errorMsg.value = e.message || '未知错误'
    loading.value = false
  }
}

onMounted(() => {
  loadReport()
})

onBeforeUnmount(() => {
  // 清理 Viewer 实例
  if (viewerInstance) {
    try {
      viewerInstance.dispose()
    } catch {
      // 忽略清理错误
    }
    viewerInstance = null
  }
})

// 参数变化时重新加载
watch(
  () => [props.reportCode, props.params],
  (newVal) => {
    console.log('[StimulsoftViewer] WATCH triggered, new params:', JSON.parse(JSON.stringify(newVal[1])))
    if (viewerContainer.value) {
      viewerContainer.value.innerHTML = ''
    }
    loadReport()
  },
  { deep: true },
)
</script>

<style scoped>
.stimulsoft-viewer-wrap {
  width: 100%;
  min-height: 400px;
}

.viewer-loading {
  padding: 24px;
}

.viewer-error {
  padding: 24px;
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 300px;
}
</style>
