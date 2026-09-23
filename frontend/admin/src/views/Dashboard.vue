<script setup lang="ts">
/**
 * 仪表盘（P1-6，需求「仪表盘负责观察数据」）
 *
 * 结构：本文件**只做装配** —— 卡片清单来自 `./dashboard/cards.ts` 的元数据，
 * 每种卡片对应一个独立组件。图表 option 由 cards.ts 的纯函数生成。
 *
 * 为什么这样拆：将来要升级成「自由拖拽仪表盘」时，只需把下面的栅格外壳
 * 换成 gridstack 容器，卡片组件与图表逻辑一行都不用改（`span`/`visible` 已预留）。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch, type Component } from 'vue'
import { get } from '@/api/request'
import {
  DASHBOARD_LAYOUT,
  KPI_CARDS,
  importStatusOption,
  jobCategoryOption,
  snapshotProgressOption,
  userGrowthOption,
} from './dashboard/cards'
import type {
  CategoryPoint,
  ImportOverviewData,
  SnapshotStatsData,
  UserGrowthPoint,
} from './dashboard/cards'
import ChartCard from './dashboard/ChartCard.vue'
import HealthCard from './dashboard/HealthCard.vue'
import KpiCard from './dashboard/KpiCard.vue'
import RecentImportCard from './dashboard/RecentImportCard.vue'

type Overview = Record<string, number>

interface HealthData {
  database: string
  scheduler: string
  llm_gateway: string
}

interface ImportJob {
  id: number
  file_name: string
  status: string
  total_rows: number
  success_count: number
  error_count: number
  created_at: string
}

const COMPONENT_MAP: Record<string, Component> = {
  kpi: KpiCard,
  chart: ChartCard,
  health: HealthCard,
  'recent-import': RecentImportCard,
}

const EMPTY_IMPORT_OVERVIEW: ImportOverviewData = {
  total_jobs: 0,
  pending: 0,
  processing: 0,
  completed: 0,
  failed: 0,
  total_rows: 0,
  success_rows: 0,
  error_rows: 0,
  last_import_at: null,
}

const EMPTY_SNAPSHOT_STATS: SnapshotStatsData = {
  total_snapshots: 0,
  matched_snapshots: 0,
  pending_snapshots: 0,
}

const loading = ref(false)
const loadedAt = ref('')
const autoRefresh = ref(false)
let timer: ReturnType<typeof setInterval> | null = null

const overview = ref<Overview | null>(null)
const userGrowth = ref<UserGrowthPoint[]>([])
const jobCategories = ref<CategoryPoint[]>([])
const importOverview = ref<ImportOverviewData | null>(null)
const snapshotStats = ref<SnapshotStatsData | null>(null)
const health = ref<HealthData | null>(null)
const recentImports = ref<ImportJob[]>([])

/**
 * 并发拉取 + **单项降级**：任一接口失败只让对应卡片显示空态，不整页报错
 * （所以用 allSettled 而不是 all）。
 */
const loadAll = async () => {
  loading.value = true
  const [ov, ug, jc, io, ss, hl, ri] = await Promise.allSettled([
    get<Overview>('/v1/admin/dashboard/overview'),
    get<UserGrowthPoint[]>('/v1/admin/dashboard/user-growth'),
    get<CategoryPoint[]>('/v1/admin/dashboard/job-categories'),
    get<ImportOverviewData>('/v1/admin/dashboard/import-overview'),
    get<SnapshotStatsData>('/v1/admin/dashboard/snapshot-stats'),
    get<HealthData>('/v1/admin/dashboard/system-health'),
    get<{ items: ImportJob[] }>('/v1/admin/import', { params: { skip: 0, limit: 5 } }),
  ])

  overview.value = ov.status === 'fulfilled' ? ov.value : null
  userGrowth.value = ug.status === 'fulfilled' ? (ug.value ?? []) : []
  jobCategories.value = jc.status === 'fulfilled' ? (jc.value ?? []) : []
  importOverview.value = io.status === 'fulfilled' ? io.value : null
  snapshotStats.value = ss.status === 'fulfilled' ? ss.value : null
  health.value = hl.status === 'fulfilled' ? hl.value : null
  recentImports.value = ri.status === 'fulfilled' ? (ri.value?.items ?? []) : []

  loadedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
  loading.value = false
}

/** 卡片 id → 组件 props（元数据驱动装配的核心；纯值，不放 ref） */
function propsFor(id: string): Record<string, unknown> {
  if (id.startsWith('kpi-')) {
    const key = id.slice('kpi-'.length)
    const meta = KPI_CARDS.find((item) => item.key === key)
    return {
      label: meta?.label ?? key,
      value: overview.value?.[key] ?? 0,
      color: meta?.color ?? 'blue',
    }
  }

  const importData = importOverview.value ?? EMPTY_IMPORT_OVERVIEW
  const stats = snapshotStats.value ?? EMPTY_SNAPSHOT_STATS

  switch (id) {
    case 'chart-user-growth':
      return {
        title: '用户增长趋势（近 30 天）',
        option: userGrowthOption(userGrowth.value),
        empty: userGrowth.value.length === 0,
        loading: loading.value,
      }
    case 'chart-job-categories':
      return {
        title: '岗位行业分布（Top 10）',
        option: jobCategoryOption(jobCategories.value),
        empty: jobCategories.value.length === 0,
        loading: loading.value,
      }
    case 'chart-import-status':
      return {
        title: '导入任务状态',
        option: importStatusOption(importData),
        empty: importData.total_jobs === 0,
        loading: loading.value,
      }
    case 'chart-snapshot-progress':
      return {
        title: '快照匹配进度',
        option: snapshotProgressOption(stats),
        empty: stats.total_snapshots === 0,
        loading: loading.value,
      }
    case 'health':
      return { health: health.value, loading: loading.value }
    case 'recent-import':
      return { items: recentImports.value, loading: loading.value }
    default:
      return {}
  }
}

const visibleCards = computed(() =>
  DASHBOARD_LAYOUT.filter((card) => card.visible).map((card) => ({
    id: card.id,
    span: card.span,
    component: COMPONENT_MAP[card.type] as Component,
    props: propsFor(card.id),
  })),
)

/** 工具栏汇总（复用已拉的导入总览，不额外请求） */
const importSummary = computed(() => {
  const data = importOverview.value
  if (!data) return ''
  return `累计 ${data.total_rows} 行 · 通过 ${data.success_rows} · 失败 ${data.error_rows}`
})

watch(autoRefresh, (on) => {
  if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
  if (on) timer = setInterval(loadAll, 60_000)
})

onBeforeUnmount(() => {
  if (timer !== null) clearInterval(timer)
})

onMounted(loadAll)
</script>

<template>
  <div class="dashboard">
    <div class="dashboard-toolbar">
      <el-button size="small" :loading="loading" @click="loadAll">刷新</el-button>
      <el-switch v-model="autoRefresh" size="small" active-text="60s 自动刷新" />
      <span v-if="loadedAt" class="toolbar-note">
        更新于 {{ loadedAt }}<template v-if="importSummary"> · {{ importSummary }}</template>
      </span>
    </div>

    <div class="dashboard-grid">
      <div
        v-for="card in visibleCards"
        :key="card.id"
        class="grid-item"
        :style="{ gridColumn: `span ${card.span}` }"
      >
        <component :is="card.component" v-bind="card.props" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.dashboard-toolbar {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 14px;
}

.toolbar-note {
  font-size: 12px;
  color: #909399;
}

/* 24 栅格：每张卡的 span 来自 cards.ts 元数据 */
.dashboard-grid {
  display: grid;
  grid-template-columns: repeat(24, minmax(0, 1fr));
  gap: 16px;
}

.grid-item {
  min-width: 0;
}
</style>
