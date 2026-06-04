<template>
  <div class="report-view-page">
    <div class="view-toolbar">
      <el-button @click="goBack" :icon="Back" size="small">返回</el-button>
      <span class="toolbar-title">{{ reportName }}</span>
    </div>
    <StimulsoftViewer
      v-if="reportCode"
      :report-code="reportCode"
      :params="reportParams"
      height="calc(100vh - 120px)"
    />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Back } from '@element-plus/icons-vue'
import StimulsoftViewer from '@/components/StimulsoftViewer.vue'

const props = defineProps({
  reportCode: { type: String, default: '' },
  order_no: { type: String, default: '' },
})

const router = useRouter()
const route = useRoute()

const reportCode = computed(() => props.reportCode || route.query.reportCode || '')
const reportName = computed(() => route.query.name || '报表预览')
const reportParams = computed(() => {
  const p = {}
  if (props.order_no || route.query.order_no) {
    p.order_no = props.order_no || route.query.order_no
  }
  return p
})

function goBack() {
  router.back()
}
</script>

<style scoped>
.report-view-page {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 60px);
}

.view-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 0;
}

.toolbar-title {
  font-size: 15px;
  font-weight: 600;
  color: #1e1e2d;
}
</style>
