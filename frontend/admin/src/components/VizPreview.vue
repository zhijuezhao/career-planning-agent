<script lang="ts">
/**
 * 后端 `viz` 载荷的形状（契约见 `backend/app/core/chat/viz.py`）。
 *
 * `<script setup>` 内不允许 ES 导出，因此类型单开一个普通 script 块
 * （与 `DetailDialog.vue` 同一手法）。
 */
export interface VizSpec {
  /** `table` = 纯表格；`radar|bar|line|pie` = 交给 ECharts 渲染 */
  kind: 'table' | 'radar' | 'bar' | 'line' | 'pie' | string
  title?: string
  /** `kind === 'table'` 时使用 */
  columns?: string[]
  rows?: (string | number | null)[][]
  /** `kind` 为 ECharts 类时使用 */
  option?: Record<string, unknown>
}
</script>

<script setup lang="ts">
/**
 * 可视化载荷渲染（C1，§11.1 的 ⑤）
 *
 * 输入是后端的 `viz` **数组**（一条消息可以有多个图）。按 `kind` 分发：
 * - `table` → `columns` + `rows`，用 `el-table`
 * - `radar|bar|line|pie` → `option`（ECharts option）
 * - 其它 → 明确提示"暂不支持"，**不静默吞掉**（否则是白屏排查困难）
 *
 * ⚠️ `EChart` 必须保持**动态导入**：`components/index.ts` 顶部写明它不能进共享 chunk
 * （会把 ≈565 kB 的 echarts 拖给所有页面）。动态导入后只有真的渲染图时才加载。
 */
import { computed, defineAsyncComponent } from 'vue'

const props = withDefaults(defineProps<{ items?: VizSpec[] | null }>(), { items: null })

const EChart = defineAsyncComponent(() => import('./EChart.vue'))

const ECHARTS_KINDS = new Set(['radar', 'bar', 'line', 'pie'])

const vizItems = computed<VizSpec[]>(() =>
  Array.isArray(props.items) ? props.items.filter((item) => !!item && typeof item === 'object') : [],
)

const isEcharts = (kind: string) => ECHARTS_KINDS.has(kind)

/** el-table 要的是"对象数组"，而后端给的是"行数组" → 这里按列序号映射成 c0/c1/... */
const rowObjects = (viz: VizSpec) =>
  (viz.rows ?? []).map((row) => {
    const obj: Record<string, unknown> = {}
    ;(viz.columns ?? []).forEach((_, index) => {
      obj[`c${index}`] = row[index] ?? ''
    })
    return obj
  })
</script>

<template>
  <div v-if="vizItems.length" class="viz-list">
    <div v-for="(viz, index) in vizItems" :key="index" class="viz-item">
      <div v-if="viz.title" class="viz-title">{{ viz.title }}</div>

      <el-table
        v-if="viz.kind === 'table'"
        :data="rowObjects(viz)"
        size="small"
        stripe
        border
        max-height="320"
      >
        <el-table-column
          v-for="(column, columnIndex) in viz.columns ?? []"
          :key="columnIndex"
          :label="column"
          :prop="`c${columnIndex}`"
          show-overflow-tooltip
        />
      </el-table>

      <EChart v-else-if="isEcharts(viz.kind) && viz.option" :option="viz.option" height="300px" />

      <el-alert
        v-else
        type="info"
        :closable="false"
        :title="`暂不支持的可视化类型：${viz.kind}`"
        show-icon
      />
    </div>
  </div>
</template>

<style scoped>
.viz-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 12px;
}

.viz-item {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 10px 12px;
  background: #fff;
}

.viz-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
}
</style>
