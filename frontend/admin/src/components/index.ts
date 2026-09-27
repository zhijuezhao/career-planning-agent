/**
 * 通用组件库统一导出（P1-1）
 * 使用方式：
 *   import { DetailDialog, MarkdownPreview } from '@/components'
 *
 * ⚠️ `EChart` **故意不在此导出**：它会把 echarts（≈565 kB / gzip 192 kB）
 * 拖进共享 chunk，导致所有页面（导入/岗位/快照/对话…）都白白加载图表库。
 * 需要图表的地方请直接 `import EChart from '@/components/EChart.vue'`，
 * 这样 echarts 只会进使用它的那个路由 chunk（当前只有仪表盘）。
 */

export { default as DetailDialog } from './DetailDialog.vue'
export { default as MarkdownPreview } from './MarkdownPreview.vue'
export { default as VizPreview } from './VizPreview.vue'

export type { DetailTag, DetailTagType } from './DetailDialog.vue'
export type { VizSpec } from './VizPreview.vue'
