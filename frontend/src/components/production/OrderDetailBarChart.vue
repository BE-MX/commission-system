<template>
  <div ref="chartRef" style="width:100%;height:100%"></div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  products: {
    type: Array,
    default: () => []
  },
  echartsTheme: {
    type: String,
    default: ''
  },
  valueField: {
    type: String,
    default: null
  },
  labelSuffix: {
    type: String,
    default: ''
  }
})

const chartRef = ref(null)
let chart = null

const COLOR_DONE = '#39d353'

function buildOption() {
  const isDark = props.echartsTheme === 'dark'
  const colorUndone = isDark ? '#30363d' : '#d0d7de'

  const data = props.products || []
  const useCustomValue = !!props.valueField

  const models = data.map(item => item.model)

  let doneValues, undoneValues
  if (useCustomValue) {
    const vf = props.valueField
    doneValues = data.map(item => item[vf] ?? 0)
    undoneValues = data.map(item => {
      const undone = 100 - (item[vf] ?? 0)
      return undone > 0 ? undone : 0
    })
  } else {
    doneValues = data.map(item => item.received_qty ?? 0)
    undoneValues = data.map(item => {
      const undone = (item.order_qty ?? 0) - (item.received_qty ?? 0)
      return undone > 0 ? undone : 0
    })
  }

  const suffix = props.labelSuffix || ''

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const name = params[0]?.axisValue || ''
        let html = `<div style="font-weight:600;margin-bottom:4px">${name}</div>`
        params.forEach(p => {
          html += `<div>${p.marker}${p.seriesName}：${p.value}${suffix}</div>`
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
      bottom: 16,
      left: 16,
      right: 24,
      containLabel: true
    },
    xAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: { fontSize: 11 }
    },
    yAxis: {
      type: 'category',
      data: models,
      axisLabel: {
        fontSize: 11,
        width: 80,
        overflow: 'truncate'
      },
      axisTick: { alignWithLabel: true }
    },
    series: [
      {
        name: '已入库',
        type: 'bar',
        stack: 'total',
        barMaxWidth: 16,
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
        barMaxWidth: 16,
        itemStyle: {
          color: colorUndone,
          borderRadius: [0, 4, 4, 0]
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
watch(() => props.products, () => {
  if (chart) {
    chart.setOption(buildOption())
  }
}, { deep: true })
</script>
