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

const emit = defineEmits(['bar-click'])

const chartRef = ref(null)
let chart = null

const COLOR_PALETTE = [
  '#56d4c5',
  '#58a6ff',
  '#bc8cff',
  '#f0b429',
  '#ff9f43',
  '#ff6b6b',
  '#a29bfe'
]

function buildOption() {
  const data = props.data || []
  const names = data.map(item => item.name)
  const values = data.map(item => item.done)

  const barData = values.map((val, idx) => ({
    value: val,
    itemStyle: {
      color: COLOR_PALETTE[idx % COLOR_PALETTE.length],
      borderRadius: [4, 4, 0, 0]
    }
  }))

  return {
    grid: {
      top: 8,
      bottom: 32,
      left: 50,
      right: 20
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const p = params[0]
        return `${p.name}<br/>${p.value} 件`
      }
    },
    xAxis: {
      type: 'category',
      data: names,
      axisLabel: {
        fontSize: 12,
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
        type: 'bar',
        data: barData,
        label: {
          show: true,
          position: 'top',
          fontSize: 12
        },
        barMaxWidth: 40
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
      emit('bar-click', params.name, params.value)
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
