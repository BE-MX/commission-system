<template>
  <div class="concept-graph">
    <div class="page-header">
      <h2>数据治理 · 全景关系图</h2>
      <div class="header-actions">
        <el-select v-model="layerFilter" multiple placeholder="层级筛选" style="width: 300px">
          <el-option v-for="(l, k) in layerLabels" :key="k" :label="l" :value="k" />
        </el-select>
        <el-select v-model="relTypeFilter" multiple placeholder="关系类型筛选" style="width: 300px">
          <el-option v-for="rt in relTypeOptions" :key="rt" :label="rt" :value="rt" />
        </el-select>
      </div>
    </div>
    <div ref="chartRef" class="graph-container" v-loading="loading"></div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import { getConceptGraph } from '@/api/governance'

const router = useRouter()

const layerLabels = {
  financial: '财务', customer: '客户', product: '产品',
  production: '生产', sales_process: '销售过程', logistics: '物流',
}

const relTypeOptions = [
  'parent_of', 'composed_of', 'derived_from',
  'influences', 'conflicts_with', 'requires', 'leads', 'lags',
]

const layerColors = {
  financial: '#E6A23C', customer: '#67C23A', product: '#F5D547',
  production: '#F56C6C', sales_process: '#9B59B6', logistics: '#909399',
}

const relColors = {
  parent_of: '#606266', composed_of: '#409EFF', derived_from: '#67C23A',
  influences: '#E6A23C', conflicts_with: '#F56C6C', requires: '#9B59B6',
  leads: '#00BCD4', lags: '#00BCD4',
}

const loading = ref(false)
const chartRef = ref(null)
const layerFilter = ref([])
const relTypeFilter = ref([])
let chart = null
let rawData = { nodes: [], edges: [] }

async function loadData() {
  loading.value = true
  try {
    const { data: res } = await getConceptGraph()
    rawData = res.data ?? res
    renderChart()
  } catch (e) {
    ElMessage.error('加载图谱数据失败')
  } finally {
    loading.value = false
  }
}

function renderChart() {
  if (!chart) return

  const filteredNodes = rawData.nodes.filter(n =>
    !layerFilter.value.length || layerFilter.value.includes(n.layer),
  )
  const nodeIds = new Set(filteredNodes.map(n => n.node_id))

  const filteredEdges = rawData.edges.filter(e =>
    nodeIds.has(e.source) && nodeIds.has(e.target) &&
    (!relTypeFilter.value.length || relTypeFilter.value.includes(e.relation_type)),
  )

  const categories = Object.entries(layerLabels).map(([k, name]) => ({ name }))

  const nodes = filteredNodes.map(n => ({
    id: n.node_id,
    name: n.label,
    symbolSize: n.status === 'active' ? 50 : 35,
    category: Object.keys(layerLabels).indexOf(n.layer),
    itemStyle: {
      color: layerColors[n.layer],
      borderColor: n.status === 'active' ? undefined : '#ccc',
      borderWidth: n.status === 'active' ? 0 : 2,
      borderType: n.status === 'pending' ? 'dashed' : 'solid',
      opacity: n.status === 'deprecated' ? 0.3 : 1,
    },
    label: { show: true, fontSize: 12 },
    value: n,
  }))

  const edges = filteredEdges.map(e => ({
    source: e.source,
    target: e.target,
    lineStyle: {
      color: relColors[e.relation_type] || '#999',
      type: e.relation_type === 'conflicts_with' ? 'dashed' : 'solid',
      width: 2,
    },
    label: { show: false },
    value: e,
  }))

  chart.setOption({
    tooltip: {
      formatter(params) {
        if (params.dataType === 'node') {
          const v = params.data.value
          return `<b>${v.label}</b> (${v.label_en})<br/>层级: ${layerLabels[v.layer]}<br/>状态: ${v.status}`
        }
        if (params.dataType === 'edge') {
          const v = params.data.value
          return `${v.relation_type}${v.description ? '<br/>' + v.description : ''}`
        }
        return ''
      },
    },
    legend: { data: categories.map(c => c.name), top: 10 },
    series: [{
      type: 'graph',
      layout: 'force',
      data: nodes,
      links: edges,
      categories,
      roam: true,
      draggable: true,
      force: { repulsion: 300, gravity: 0.1, edgeLength: 150 },
      emphasis: { focus: 'adjacency', lineStyle: { width: 4 } },
    }],
  }, true)

  chart.on('click', (params) => {
    if (params.dataType === 'node') {
      router.push(`/governance/concepts/${params.data.id}`)
    }
  })
}

watch([layerFilter, relTypeFilter], () => renderChart())

onMounted(() => {
  if (chartRef.value) {
    chart = echarts.init(chartRef.value)
    loadData()
  }
  window.addEventListener('resize', () => chart?.resize())
})

onBeforeUnmount(() => {
  chart?.dispose()
})
</script>

<style scoped>
.concept-graph {
  padding: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.page-header h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.graph-container {
  width: 100%;
  height: calc(100vh - 160px);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-bg-color);
}
</style>
