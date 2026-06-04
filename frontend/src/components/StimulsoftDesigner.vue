<template>
  <div class="stimulsoft-designer-wrap">
    <!-- 加载中 -->
    <div v-if="loading" class="designer-loading">
      <el-skeleton :rows="8" animated />
      <p style="text-align: center; color: #909399; margin-top: 16px;">正在加载报表设计器...</p>
    </div>

    <!-- 错误 -->
    <div v-else-if="errorMsg" class="designer-error">
      <el-result icon="error" title="设计器加载失败" :sub-title="errorMsg">
        <template #extra>
          <el-button type="primary" @click="initDesigner">重新加载</el-button>
        </template>
      </el-result>
    </div>

    <!-- 设计器容器 -->
    <div
      v-show="!loading && !errorMsg"
      ref="designerContainer"
      :style="{ height }"
    />
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { useStimulsoft } from '@/composables/useStimulsoft'
import { getReportData } from '@/api/reportCenter'

const props = defineProps({
  /** 报表编码 */
  reportCode: { type: String, required: true },
  /** .mrt 模板内容（JSON 字符串） */
  templateContent: { type: String, default: '' },
  /** 查询参数，用于加载样例数据 */
  params: { type: Object, default: () => ({}) },
  /** 容器高度 */
  height: { type: String, default: '85vh' },
})

const emit = defineEmits(['save'])

const loading = ref(true)
const errorMsg = ref(null)
const designerContainer = ref(null)

const { createDesigner } = useStimulsoft()
let designerInstance = null

async function initDesigner() {
  if (!designerContainer.value) return

  loading.value = true
  errorMsg.value = null

  try {
    const Stimulsoft = window.Stimulsoft

    const report = new Stimulsoft.Report.StiReport()

    // 加载模板
    if (props.templateContent) {
      report.load(props.templateContent)
    }

    // 清除数据库连接
    report.dictionary.databases.clear()

    // 尝试加载样例数据
    try {
      const dataRes = await getReportData(props.reportCode, props.params)
      const reportData = dataRes.data?.data || dataRes.data
      if (reportData) {
        const dataSet = new Stimulsoft.System.Data.DataSet('data')
        dataSet.readJson(reportData)
        report.regData('data', 'data', dataSet)
        report.dictionary.synchronize()
      }
    } catch {
      // 没有样例数据也能打开设计器
    }

    // 创建 Designer
    designerInstance = await createDesigner(
      designerContainer.value,
      report,
      (mrtText) => {
        emit('save', mrtText)
      },
    )

    loading.value = false
  } catch (e) {
    console.error('设计器加载失败:', e)
    errorMsg.value = e.message || '未知错误'
    loading.value = false
  }
}

onMounted(() => {
  initDesigner()
})

onBeforeUnmount(() => {
  if (designerInstance) {
    try {
      designerInstance.dispose()
    } catch {
      // 忽略
    }
    designerInstance = null
  }
})
</script>

<style scoped>
.stimulsoft-designer-wrap {
  width: 100%;
  min-height: 400px;
}

.designer-loading {
  padding: 24px;
}

.designer-error {
  padding: 24px;
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 300px;
}
</style>
