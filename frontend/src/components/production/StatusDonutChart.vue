<template>
  <div ref="chartRef" style="width:100%;height:100%"></div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  data: {
    type: Array,
    default: () => []
  },
  echartsTheme: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['sector-click'])

const chartRef = ref(null)
let chart = null

function getColor(varName) {
  return getComputedStyle(document.documentElement).getPropertyValue(varName).trim()
}

function buildOption() {
  const isDark = props.echartsTheme === 'dark'
  const colorUnstarted = isDark ? '#484f58' : '#afb8c1'
  const colorInProgress = getColor('--db-accent-blue') || '#58a6ff'
  const colorDone = getColor('--db-accent-cyan') || '#56d4c5'

  const colorMap = {
    '未开始': colorUnstarted,
    '进行中': colorInProgress,
    '已完成': colorDone
  }

  const seriesData = (props.data || []).map(item => ({
    name: item.name,
    value: item.value,
    itemStyle: { color: colorMap[item.name] || '#888' }
  }))

  return {
    tooltip: {
      trigger: 'item',
      formatter: '{b}: {c}件 ({d}%)'
    },
    legend: {
      bottom: '2%',
      left: 'center',
      itemWidth: 10,
      itemHeight: 10,
      textStyle: {
        fontSize: 12
      }
    },
    series: [
      {
        type: 'pie',
        radius: ['45%', '70%'],
        center: ['50%', '45%'],
        avoidLabelOverlap: false,
        label: {
          show: true,
          formatter: '{b}\n{c}件',
          lineHeight: 18,
          fontSize: 12
        },
        labelLine: {
          length: 12,
          length2: 8
        },
        emphasis: {
          scale: true,
          scaleSize: 6
        },
        data: seriesData
      }
    ]
  }
}

function initChart() {
  if (chart) {
    chart.dispose()
    chart = null
  }
  if (!chartRef.value) return
  chart = echarts.init(chartRef.value, props.echartsTheme || '')
  chart.setOption(buildOption())
  chart.on('click', (params) => {
    if (params.componentType === 'series') {
      emit('sector-click', params.name)
    }
  })
}

onMounted(() => initChart())
onUnmounted(() => { chart?.dispose() })

watch(() => props.echartsTheme, () => initChart())
watch(() => props.data, () => {
  if (chart) {
    chart.setOption(buildOption())
  }
}, { deep: true })
</script>
