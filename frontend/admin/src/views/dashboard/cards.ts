/**
 * 仪表盘卡片元数据与图表配置（P1-6）
 *
 * 设计意图（**可升级结构**）：
 * - 布局、显隐、栅格宽（`span`）全部集中在 `DASHBOARD_LAYOUT`，`Dashboard.vue` 只做装配；
 * - 图表 option 由纯函数生成（吃数据、吐配置），便于单测与复用；
 * - 将来升级到「自由拖拽」（gridstack + localStorage）只需替换 `Dashboard.vue` 的栅格外壳，
 *   **卡片组件与图表逻辑零重写**；`span` / `visible` 就是为此预留的字段。
 */
import type { EChartsCoreOption } from 'echarts/core'

// ── 卡片元数据 ──────────────────────────────────────────────────────────────

export type DashboardCardType = 'kpi' | 'chart' | 'health' | 'recent-import'

export interface DashboardCardMeta {
  id: string
  type: DashboardCardType
  title: string
  /** 24 栅格宽（4 = 六分之一，12 = 半行） */
  span: number
  visible: boolean
}

export interface KpiMeta {
  key: string
  label: string
  color: string
}

export const KPI_CARDS: KpiMeta[] = [
  { key: 'total_users', label: '用户总数', color: 'blue' },
  { key: 'total_resumes', label: '简历总数', color: 'green' },
  { key: 'total_job_profiles', label: '岗位画像', color: 'orange' },
  { key: 'total_matches', label: '已匹配快照', color: 'purple' },
  { key: 'total_reports', label: '报告数量', color: 'cyan' },
  { key: 'total_chat_sessions', label: '对话会话', color: 'pink' },
]

export const DASHBOARD_LAYOUT: DashboardCardMeta[] = [
  ...KPI_CARDS.map<DashboardCardMeta>((kpi) => ({
    id: `kpi-${kpi.key}`,
    type: 'kpi',
    title: kpi.label,
    span: 4,
    visible: true,
  })),
  { id: 'chart-user-growth', type: 'chart', title: '用户增长趋势（近 30 天）', span: 12, visible: true },
  { id: 'chart-job-categories', type: 'chart', title: '岗位行业分布（Top 10）', span: 12, visible: true },
  { id: 'chart-import-status', type: 'chart', title: '导入任务状态', span: 12, visible: true },
  { id: 'chart-snapshot-progress', type: 'chart', title: '快照匹配进度', span: 12, visible: true },
  { id: 'health', type: 'health', title: '系统健康', span: 12, visible: true },
  { id: 'recent-import', type: 'recent-import', title: '最近导入', span: 12, visible: true },
]

// ── 数据类型 ────────────────────────────────────────────────────────────────

export interface UserGrowthPoint {
  date: string
  count: number
}

export interface CategoryPoint {
  category: string
  count: number
}

export interface ImportOverviewData {
  total_jobs: number
  pending: number
  processing: number
  completed: number
  failed: number
  total_rows: number
  success_rows: number
  error_rows: number
  last_import_at: string | null
}

export interface SnapshotStatsData {
  total_snapshots: number
  matched_snapshots: number
  pending_snapshots: number
}

// ── 主题常量（与 admin 现有配色一致）────────────────────────────────────────

export const CHART_COLORS = {
  primary: '#667eea',
  success: '#22c55e',
  warning: '#e6a23c',
  danger: '#f56c6c',
  muted: '#c0c4cc',
  axis: '#909399',
  split: '#f0f2f5',
}

const axisLabel = { color: CHART_COLORS.axis, fontSize: 11 }

// ── 图表 option 生成器（纯函数）─────────────────────────────────────────────

export function userGrowthOption(rows: UserGrowthPoint[]): EChartsCoreOption {
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 44, right: 16, top: 20, bottom: 26 },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: rows.map((row) => row.date),
      axisLabel,
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel,
      splitLine: { lineStyle: { color: CHART_COLORS.split } },
    },
    series: [
      {
        type: 'line',
        smooth: true,
        symbolSize: 6,
        data: rows.map((row) => row.count),
        itemStyle: { color: CHART_COLORS.primary },
        areaStyle: { opacity: 0.12 },
      },
    ],
  }
}

export function jobCategoryOption(rows: CategoryPoint[]): EChartsCoreOption {
  const top = [...rows].sort((a, b) => b.count - a.count).slice(0, 10).reverse()
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 96, right: 24, top: 12, bottom: 24 },
    xAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel,
      splitLine: { lineStyle: { color: CHART_COLORS.split } },
    },
    yAxis: { type: 'category', data: top.map((row) => row.category), axisLabel },
    series: [
      {
        type: 'bar',
        barWidth: 12,
        data: top.map((row) => row.count),
        itemStyle: { color: CHART_COLORS.primary, borderRadius: [0, 4, 4, 0] },
      },
    ],
  }
}

export function importStatusOption(data: ImportOverviewData): EChartsCoreOption {
  const items = [
    { name: '成功', value: data.completed, color: CHART_COLORS.success },
    { name: '失败', value: data.failed, color: CHART_COLORS.danger },
    { name: '处理中', value: data.processing, color: CHART_COLORS.warning },
    { name: '待处理', value: data.pending, color: CHART_COLORS.axis },
  ].filter((item) => item.value > 0)

  return {
    tooltip: { trigger: 'item' },
    legend: { bottom: 0, textStyle: axisLabel },
    series: [
      {
        type: 'pie',
        radius: ['46%', '68%'],
        center: ['50%', '44%'],
        label: { show: false },
        data: items.map((item) => ({
          name: item.name,
          value: item.value,
          itemStyle: { color: item.color },
        })),
      },
    ],
  }
}

export function snapshotProgressOption(data: SnapshotStatsData): EChartsCoreOption {
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { bottom: 0, textStyle: axisLabel },
    grid: { left: 60, right: 24, top: 16, bottom: 30 },
    xAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel,
      splitLine: { lineStyle: { color: CHART_COLORS.split } },
    },
    yAxis: { type: 'category', data: ['快照'], axisLabel },
    series: [
      {
        name: '已匹配',
        type: 'bar',
        stack: 'total',
        barWidth: 22,
        data: [data.matched_snapshots],
        itemStyle: { color: CHART_COLORS.success },
      },
      {
        name: '待匹配',
        type: 'bar',
        stack: 'total',
        barWidth: 22,
        data: [data.pending_snapshots],
        itemStyle: { color: CHART_COLORS.muted },
      },
    ],
  }
}
