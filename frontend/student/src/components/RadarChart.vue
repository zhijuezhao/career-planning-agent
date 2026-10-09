<script setup lang="ts">
/**
 * 雷达图组件
 * 基于 ECharts 的能力雷达图，支持响应式
 */
import { ref, onMounted, watch } from 'vue'
import { useResizeObserver } from '@vueuse/core'
import * as echarts from 'echarts/core'
import { RadarChart } from 'echarts/charts'
import { CanvasRenderer } from 'echarts/renderers'
import { TooltipComponent } from 'echarts/components'

echarts.use([RadarChart, CanvasRenderer, TooltipComponent])

interface RadarData {
  indicators: { name: string; max: number }[]
  values: number[]
  total_score?: number
}

const props = defineProps<{
  data: RadarData | null
  height?: string
}>()

const chartRef = ref<HTMLElement>()
let chartInstance: echarts.ECharts | null = null

function render() {
  if (!chartRef.value || !props.data) return
  if (!chartInstance) {
    chartInstance = echarts.init(chartRef.value)
  }
  chartInstance.setOption({
    radar: {
      indicator: props.data.indicators,
      shape: 'polygon',
      splitNumber: 4,
      axisName: { color: '#475569', fontSize: 12 },
      splitLine: { lineStyle: { color: '#e2e8f0' } },
      splitArea: { show: false },
      axisLine: { lineStyle: { color: '#e2e8f0' } },
    },
    series: [{
      type: 'radar',
      data: [{
        value: props.data.values,
        areaStyle: { color: 'rgba(99, 102, 241, 0.15)' },
        lineStyle: { color: '#6366f1', width: 2 },
        itemStyle: { color: '#6366f1' },
        symbol: 'circle',
        symbolSize: 6,
      }],
    }],
    tooltip: { trigger: 'item' },
  })
}

onMounted(() => {
  render()
  if (chartRef.value) {
    useResizeObserver(chartRef.value, () => chartInstance?.resize())
  }
})

watch(() => props.data, () => {
  render()
}, { deep: true })
</script>

<template>
  <div class="radar-chart-container">
    <div v-if="data" ref="chartRef" class="radar-chart" :style="{ height: height || '280px' }"></div>
    <div v-else class="radar-empty">
      <p>暂无雷达图数据</p>
    </div>
  </div>
</template>

<style scoped>
.radar-chart-container {
  width: 100%;
}
.radar-chart {
  width: 100%;
}
.radar-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 200px;
  color: var(--c-text-3);
  font-size: 13px;
}
</style>
