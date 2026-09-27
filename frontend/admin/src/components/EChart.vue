<script setup lang="ts">
/**
 * ECharts 包装（P1-1）
 *
 * 按需注册（tree-shaking）：只引入项目实际用到的**折线/柱状/饼图/雷达图** + 基础组件，
 * 避免把整个 echarts 打进 admin bundle。
 * ⚠️ 雷达图（P5）需要 `RadarChart` **和** `RadarComponent` 两样：只注册 series 不注册
 * coordinate 组件的话，ECharts 只会打一条警告、**图静默不渲染**（计划 §19.6 坑 2 预告过）。
 * 自适应：用 `ResizeObserver` 监听容器（侧边栏折叠、窗口缩放、栅格变化都能跟上）。
 */
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import * as echarts from 'echarts/core'
import type { EChartsCoreOption, EChartsType } from 'echarts/core'
import { BarChart, LineChart, PieChart, RadarChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  RadarComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  RadarChart,
  GridComponent,
  LegendComponent,
  RadarComponent,
  TitleComponent,
  TooltipComponent,
  CanvasRenderer,
])

const props = withDefaults(
  defineProps<{
    option: EChartsCoreOption
    height?: string
  }>(),
  {
    height: '280px',
  },
)

const container = ref<HTMLDivElement | null>(null)
const chart = shallowRef<EChartsType | null>(null)
let observer: ResizeObserver | null = null

function render() {
  if (!chart.value) return
  // notMerge=true：切换数据源时清掉上一份 series，避免残影
  chart.value.setOption(props.option, true)
}

onMounted(() => {
  if (!container.value) return
  chart.value = echarts.init(container.value)
  render()

  observer = new ResizeObserver(() => chart.value?.resize())
  observer.observe(container.value)
})

watch(() => props.option, render, { deep: true })

onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
  chart.value?.dispose()
  chart.value = null
})
</script>

<template>
  <div ref="container" class="echart" :style="{ height }" />
</template>

<style scoped>
.echart {
  width: 100%;
}
</style>
