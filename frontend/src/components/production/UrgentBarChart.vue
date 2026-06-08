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

const chartRef = ref(null)
let chart = null

const COLOR_DONE = '#39d353'
const COLOR_UNDONE = '#ff6b6b'

function buildOption() {
  const data = props.data || []
  const models = data.map(item => item.model)
  const doneValues = data.map(item => item.received_qty ?? 0)
  const undoneValues = data.map(item => {
    const undone = (item.order_qty ?? 0) - (item.received_qty ?? 0)
    return undone > 0 ? undone : 0
  })

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const name = params[0]?.axisValue || ''
        let html = `<div style="font-weight:600;margin-bottom:4px">${name}</div>`
        params.forEach(p => {
          html += `<div>${p.marker}${p.seriesName}：${p.value} 件</div>`
        })
        return html
      }
    },
    legend: {
      top: 0,
      right: 8,
      itemWidth: 10,
      itemHeight: 10,
      data: ['已入库', '未入库']
    },
    grid: {
      top: 28,
      bottom: 40,
      left: 50,
      right: 16
    },
    xAxis: {
      type: 'category',
      data: models,
      axisLabel: {
        rotate: 20,
        fontSize: 11,
        interval: 0
      },
      axisTick: { alignWithLabel: true }
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: { fontSize: 12 }
    },
    series: [
      {
        name: '已入库',
        type: 'bar',
        stack: 'total',
        barMaxWidth: 20,
        itemStyle: {
          color: COLOR_DONE,
          borderRadius: [0, 0, 0, 0]
        },
        data: doneValues,
        label: {
          show: false
        }
      },
      {
        name: '未入库',
        type: 'bar',
        stack: 'total',
        barMaxWidth: 20,
        itemStyle: {
          color: COLOR_UNDONE,
          borderRadius: [3, 3, 0, 0]
        },
        data: undoneValues,
        label: {
          show: false
        }
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
