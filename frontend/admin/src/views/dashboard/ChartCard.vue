<script setup lang="ts">
/** 图表卡（P1-6）：标题 + ECharts（无数据时统一走 el-empty，不画空坐标系） */
import type { EChartsCoreOption } from 'echarts/core'
// 直接引文件（不走 '@/components' barrel）：让 echarts 只进仪表盘 chunk，
// 不被其它页面共享加载，详见 components/index.ts 的说明。
import EChart from '@/components/EChart.vue'

withDefaults(
  defineProps<{
    title: string
    option: EChartsCoreOption
    empty?: boolean
    loading?: boolean
    height?: string
    emptyText?: string
  }>(),
  {
    empty: false,
    loading: false,
    height: '280px',
    emptyText: '暂无数据',
  },
)
</script>

<template>
  <el-card class="chart-card" v-loading="loading">
    <template #header>
      <span class="card-title">{{ title }}</span>
    </template>
    <el-empty v-if="empty" :description="emptyText" :image-size="60" />
    <EChart v-else :option="option" :height="height" />
  </el-card>
</template>

<style scoped>
.chart-card {
  border-radius: 12px;
  border: 1px solid #e6e6e6;
  height: 100%;
  box-sizing: border-box;
}

.card-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}
</style>
