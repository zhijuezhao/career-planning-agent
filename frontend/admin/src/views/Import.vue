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
import { DetailDialog } from '@/components'
import type { DetailTag } from '@/components'
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
  created_at: string
  updated_at: string
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
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
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

.sep {
  margin: 0 2px;
  color: #c0c4cc;
}
</style>
