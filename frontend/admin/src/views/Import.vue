<script setup lang="ts">
/**
 * 数据导入（P1-2，需求 1）
 *
 * 本轮改动：补齐「导入时间 / 导入条数 / 进度」三列 + 状态中文化 + 失败原因预览卡。
 * 交互沿用原有「上传即自动开始处理 → 轮询进度」流程（S7-3 起后端已是真流水线）。
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { UploadRequestOptions } from 'element-plus'
import { get, post } from '@/api/request'
import { DetailDialog, LinkEnrichPanel } from '@/components'
import type { DetailTag } from '@/components'
import {
  enrichCell,
  enrichMarkdown,
  enrichTags,
  type EnrichCell,
  type LinkEnrichStats,
} from '@/utils/linkEnrich'
import { errorsToMarkdown, formatBytes, formatDateTime, progressPercent } from '@/utils/preview'

interface ImportJob {
  id: number
  file_name: string
  file_size: number
  status: string
  total_rows: number
  processed_rows: number
  success_count: number
  error_count: number
  errors: string[] | null
  /** 落库统计（persist）与表结构检测（schema）——见后端 `_import_runner._apply_stage` */
  stats: ImportStats | null
  created_at: string
  updated_at: string
}

/** 表结构检测结果（`schema_detect.SchemaProfile`） */
interface ImportSchema {
  genre?: string
  fields?: string[]
  has_recruiting_fields?: boolean
  has_career_markers?: boolean
}

/** 落库统计（`job_persist_service.persist_import_rows`） */
interface ImportPersistStats {
  raw_written?: number
  profiles_new?: number
  profiles_updated?: number
  failed?: number
}

interface ImportStats {
  schema?: ImportSchema
  persist?: ImportPersistStats
  /** B3-1/B3-2 链接富化统计（B3-3 起在导入页专门展示） */
  link_enrich?: LinkEnrichStats
}

/** 体裁 → 中文（与后端 schema_detect 的取值一致） */
const GENRE_LABELS: Record<string, string> = {
  job_posting: '招聘岗位表',
  career_roadmap: '职业发展路线表',
  mixed: '混合表（既有招聘字段又有路线字段）',
  unknown: '未识别体裁',
}

type TagType = 'success' | 'danger' | 'warning' | 'info'

/** 后端状态 → 中文语义（completed 即需求里的 success） */
const STATUS_META: Record<string, { label: string; type: TagType }> = {
  pending: { label: '待处理', type: 'info' },
  processing: { label: '处理中', type: 'warning' },
  completed: { label: '成功', type: 'success' },
  failed: { label: '失败', type: 'danger' },
}

const loading = ref(false)
const tableData = ref<ImportJob[]>([])
const total = ref(0)
const progress = ref(0)
const currentJobId = ref<number | null>(null)
let pollTimer: ReturnType<typeof setInterval> | null = null

const query = reactive({
  page: 1,
  limit: 20,
})

const statusOf = (status: string) => STATUS_META[status] ?? { label: status, type: 'info' as TagType }

const fetchData = async () => {
  loading.value = true
  try {
    const res = await get<{ items: ImportJob[]; total: number }>('/v1/admin/import', {
      params: { skip: (query.page - 1) * query.limit, limit: query.limit },
    })
    tableData.value = res.items
    total.value = res.total
  } catch {
    // error handled by interceptor
  } finally {
    loading.value = false
  }
}

const handleUpload = async (options: UploadRequestOptions) => {
  const formData = new FormData()
  formData.append('file', options.file)
  try {
    const res = await post<{ id: number }>('/v1/admin/import/upload', formData)
    ElMessage.success('上传成功，开始处理')
    currentJobId.value = res.id
    await fetchData()
    await handleProcess(res.id)
  } catch {
    // error handled by interceptor
  }
}

const handleProcess = async (jobId: number) => {
  try {
    await post(`/v1/admin/import/${jobId}/process`)
    startProgressPolling(jobId)
  } catch {
    // error handled by interceptor
  }
}

/** 轮询：既更新顶部总进度条，也原地刷新表格里那一行的计数 */
const startProgressPolling = (jobId: number) => {
  stopProgressPolling()
  pollTimer = setInterval(async () => {
    try {
      const res = await get<{
        progress_pct: number
        status: string
        total_rows: number
        processed_rows: number
        success_count: number
        error_count: number
      }>(`/v1/admin/import/${jobId}/progress`)
      progress.value = res.progress_pct

      const row = tableData.value.find((item) => item.id === jobId)
      if (row) {
        row.status = res.status
        row.total_rows = res.total_rows
        row.processed_rows = res.processed_rows
        row.success_count = res.success_count
        row.error_count = res.error_count
      }

      if (res.status === 'completed' || res.status === 'failed') {
        stopProgressPolling()
        ElMessage.success(res.status === 'completed' ? '导入完成' : '导入失败，可点「原因」查看')
        await fetchData()
      }
    } catch {
      stopProgressPolling()
    }
  }, 1000)
}

const stopProgressPolling = () => {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

// ── 失败原因预览卡 ──────────────────────────────────────────────────────────

const detailVisible = ref(false)
const detailJob = ref<ImportJob | null>(null)

const openDetail = (row: ImportJob) => {
  detailJob.value = row
  detailVisible.value = true
}

const detailTitle = computed(() =>
  detailJob.value?.status === 'failed' ? '导入失败原因' : '导入任务详情',
)

const detailSubtitle = computed(() => {
  const job = detailJob.value
  if (!job) return ''
  return `${job.file_name} · 文件 ${formatBytes(job.file_size)} · ${formatDateTime(job.created_at)}`
})

const detailTags = computed<DetailTag[]>(() => {
  const job = detailJob.value
  if (!job) return []
  const meta = statusOf(job.status)
  return [
    { text: meta.label, type: meta.type },
    { text: `共 ${job.total_rows} 条`, type: 'info' },
    { text: `失败 ${job.error_count} 条`, type: job.error_count > 0 ? 'danger' : 'info' },
  ]
})

const detailMarkdown = computed(() => errorsToMarkdown(detailJob.value?.errors))

// ── 统计预览卡（落库统计 + 表结构/体裁检测）────────────────────────────────
// 「判 D 太多」时最需要看的就是体裁：职业发展路线表用招聘口径评分会被结构性判死。

const statsVisible = ref(false)
const statsJob = ref<ImportJob | null>(null)

const openStats = (row: ImportJob) => {
  statsJob.value = row
  statsVisible.value = true
}

const statsTags = computed<DetailTag[]>(() => {
  const job = statsJob.value
  if (!job) return []
  const persist = job.stats?.persist ?? {}
  const genre = job.stats?.schema?.genre
  const tags: DetailTag[] = []
  if (genre) tags.push({ text: GENRE_LABELS[genre] ?? genre, type: 'info' })
  tags.push({ text: `入库 ${persist.raw_written ?? 0} 行`, type: 'success' })
  tags.push({ text: `新建 ${persist.profiles_new ?? 0}`, type: 'info' })
  tags.push({ text: `更新 ${persist.profiles_updated ?? 0}`, type: 'info' })
  if ((persist.failed ?? 0) > 0) {
    tags.push({ text: `失败 ${persist.failed} 行`, type: 'danger' })
  }
  // 2026-09-30：D 级行不再归档进 job_raw_data（后端不再产出 raw_written_rejected），
  // 未入库的淘汰数直接用工单的 error_count 表达。
  const rejectedCount = job.error_count ?? 0
  if (rejectedCount > 0) {
    tags.push({ text: `淘汰 ${rejectedCount} 行（未入库）`, type: 'warning' })
  }
  return tags
})

const statsMarkdown = computed(() => {
  const stats = statsJob.value?.stats
  if (!stats) return ''
  const lines: string[] = []
  const schema = stats.schema
  if (schema?.genre) {
    lines.push(`**表体裁**：${GENRE_LABELS[schema.genre] ?? schema.genre}（\`${schema.genre}\`）`)
    if (schema.has_career_markers) {
      lines.push('- 检测到职业路线特征列（技能/证书/晋升/换岗）→ 按**自适应口径**评分')
    }
    if (schema.has_recruiting_fields) {
      lines.push('- 检测到招聘字段（公司/城市/薪资）')
    }
    if (schema.fields?.length) {
      lines.push(`- 归一化后字段：\`${schema.fields.join('`, `')}\``)
    }
  }
  const persist = stats.persist
  if (persist) {
    lines.push(
      '',
      `**落库**：入库 ${persist.raw_written ?? 0} 行` +
        `（新建 ${persist.profiles_new ?? 0} / 更新 ${persist.profiles_updated ?? 0}），` +
        `淘汰 ${statsJob.value?.error_count ?? 0} 行（未入库），失败 ${persist.failed ?? 0} 行`,
    )
  }
  return lines.join('\n')
})

// ── 链接富化统计（B3-3）────────────────────────────────────────────────────
// 「专门展示」：把 `stats.link_enrich` 从通用「stats JSON」页签里拎出来，按口径分组渲染。
// 文案与数字全部来自 `@/utils/linkEnrich`（纯函数），这里只管接线。
// ⚠️ 口径说明（含易读错的 rows_enriched / token / 预算截断）写在该模块头部。

const enrichVisible = ref(false)
const enrichJob = ref<ImportJob | null>(null)

const openEnrich = (row: ImportJob) => {
  enrichJob.value = row
  enrichVisible.value = true
}

const enrichStats = computed<LinkEnrichStats | null>(
  () => enrichJob.value?.stats?.link_enrich ?? null,
)

const enrichDialogTags = computed<DetailTag[]>(() => enrichTags(enrichStats.value))
const enrichDialogMarkdown = computed(() => enrichMarkdown(enrichStats.value))

/** 列表「链接富化」列的摘要：预计算成 id → 单元格，避免模板里重复调用 */
const enrichCells = computed<Record<number, EnrichCell | null>>(() => {
  const out: Record<number, EnrichCell | null> = {}
  for (const row of tableData.value) out[row.id] = enrichCell(row.stats?.link_enrich)
  return out
})

onMounted(fetchData)
onBeforeUnmount(stopProgressPolling)
</script>

<template>
  <div>
    <el-card class="data-card">
      <div class="toolbar">
        <el-upload
          :show-file-list="false"
          :http-request="handleUpload"
          accept=".xlsx,.xls,.csv"
        >
          <el-button type="primary">上传文件</el-button>
        </el-upload>
        <el-button @click="fetchData">刷新</el-button>
        <div v-if="currentJobId !== null && progress > 0 && progress < 100" class="running">
          <span class="running-text">任务 #{{ currentJobId }} 处理中</span>
          <el-progress :percentage="progress" style="width: 200px" />
        </div>
      </div>

      <el-table v-loading="loading" :data="tableData" stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="file_name" label="文件名" min-width="180" show-overflow-tooltip />
        <el-table-column label="文件大小" width="100">
          <template #default="{ row }">{{ formatBytes(row.file_size) }}</template>
        </el-table-column>
        <el-table-column label="导入时间" width="170">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="statusOf(row.status).type" size="small">
              {{ statusOf(row.status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="导入条数" width="100">
          <template #default="{ row }">{{ row.total_rows }}</template>
        </el-table-column>
        <el-table-column label="成功/失败" width="110">
          <template #default="{ row }">
            <span class="ok">{{ row.success_count }}</span>
            <span class="sep">/</span>
            <span :class="row.error_count > 0 ? 'bad' : 'muted'">{{ row.error_count }}</span>
          </template>
        </el-table-column>
        <el-table-column label="进度" min-width="180">
          <template #default="{ row }">
            <div class="progress-cell">
              <el-progress
                :percentage="progressPercent(row.processed_rows, row.total_rows)"
                :stroke-width="6"
                :show-text="false"
                :status="row.status === 'failed' ? 'exception' : undefined"
                class="progress-bar"
              />
              <span class="progress-text">{{ row.processed_rows }}/{{ row.total_rows }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="链接富化" min-width="170">
          <template #default="{ row }">
            <span v-if="!enrichCells[row.id]" class="muted">—</span>
            <span
              v-else
              :class="enrichCells[row.id]?.truncated ? 'warn' : 'enrich-summary'"
              :title="enrichCells[row.id]?.truncated ? '本次触达预算上限，富化被截断' : undefined"
            >
              {{ enrichCells[row.id]?.text }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="210" fixed="right">
          <template #default="{ row }">
            <el-button
              type="primary"
              size="small"
              link
              :disabled="!row.stats?.link_enrich"
              @click="openEnrich(row)"
            >
              富化
            </el-button>
            <el-button
              type="primary"
              size="small"
              link
              :disabled="!row.stats"
              @click="openStats(row)"
            >
              统计
            </el-button>
            <el-button
              type="primary"
              size="small"
              link
              :disabled="!row.errors || row.errors.length === 0"
              @click="openDetail(row)"
            >
              原因
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="query.page"
        :page-size="query.limit"
        :total="total"
        layout="total, prev, pager, next"
        @current-change="fetchData"
      />
    </el-card>

    <DetailDialog
      v-model="detailVisible"
      :title="detailTitle"
      :subtitle="detailSubtitle"
      :tags="detailTags"
      :markdown="detailMarkdown"
      :json="detailJob?.errors ?? []"
      json-label="errors JSON"
      empty-text="（无失败原因）"
    />

    <DetailDialog
      v-model="statsVisible"
      title="导入统计"
      :subtitle="statsJob ? `${statsJob.file_name} · 任务 #${statsJob.id}` : ''"
      :tags="statsTags"
      :markdown="statsMarkdown"
      :json="statsJob?.stats ?? {}"
      json-label="stats JSON"
      empty-text="（本次导入无统计信息）"
    />

    <DetailDialog
      v-model="enrichVisible"
      title="链接富化统计"
      :subtitle="enrichJob ? `${enrichJob.file_name} · 任务 #${enrichJob.id}` : ''"
      :tags="enrichDialogTags"
      :markdown="enrichDialogMarkdown"
      :json="enrichStats ?? {}"
      json-label="link_enrich JSON"
      empty-text="（本次导入没有链接富化统计）"
      width="780px"
      max-height="68vh"
    >
      <template #preview-extra>
        <LinkEnrichPanel :stats="enrichStats" />
      </template>
    </DetailDialog>
  </div>
</template>

<style scoped>
.data-card {
  border-radius: 12px;
  border: 1px solid #e6e6e6;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
}

.running {
  display: flex;
  align-items: center;
  gap: 10px;
}

.running-text {
  font-size: 12px;
  color: #909399;
}

.progress-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}

.progress-bar {
  flex: 1;
  min-width: 80px;
}

.progress-text {
  font-size: 12px;
  color: #909399;
  white-space: nowrap;
}

.ok {
  color: #67c23a;
}

.bad {
  color: #f56c6c;
}

.muted {
  color: #909399;
}

/* 链接富化摘要（B3-3）：预算截断时改用警示色，正常时弱化以免抢主列的注意力 */
.enrich-summary {
  font-size: 12px;
  color: #606266;
}

.warn {
  font-size: 12px;
  font-weight: 600;
  color: #b88230;
}

.sep {
  margin: 0 2px;
  color: #c0c4cc;
}
</style>
