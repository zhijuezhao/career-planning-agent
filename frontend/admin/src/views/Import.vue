<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { UploadRequestOptions } from 'element-plus'
import { get, post, put, remove } from '@/api/request'

interface ImportJob {
  id: number
  file_name: string
  file_size: number
  status: string
  total_rows: number
  processed_rows: number
  success_count: number
  error_count: number
  created_at: string
}

const loading = ref(false)
const tableData = ref<ImportJob[]>([])
const total = ref(0)
const progress = ref(0)
const currentJobId = ref<number | null>(null)

const query = reactive({
  page: 1,
  limit: 20,
})

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
    ElMessage.success('上传成功')
    currentJobId.value = res.id
    await handleProcess(res.id)
    fetchData()
  } catch {
    // error handled by interceptor
  }
}

const handleProcess = async (jobId: number) => {
  try {
    await post(`/v1/admin/import/${jobId}/process`)
    ElMessage.success('开始处理')
    startProgressPolling(jobId)
  } catch {
    // error handled by interceptor
  }
}

const startProgressPolling = (jobId: number) => {
  const timer = setInterval(async () => {
    try {
      const res = await get<{ progress_pct: number; status: string }>(`/v1/admin/import/${jobId}/progress`)
      progress.value = res.progress_pct
      if (res.status === 'completed' || res.status === 'failed') {
        clearInterval(timer)
        ElMessage.success(res.status === 'completed' ? '导入完成' : '导入失败')
        fetchData()
      }
    } catch {
      clearInterval(timer)
    }
  }, 1000)
}

onMounted(fetchData)
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
        <el-progress
          v-if="progress > 0 && progress < 100"
          :percentage="progress"
          style="width: 200px"
        />
      </div>

      <el-table v-loading="loading" :data="tableData" stripe>
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="file_name" label="文件名" />
        <el-table-column label="大小" width="100">
          <template #default="{ row }">
            {{ (row.file_size / 1024).toFixed(1) }} KB
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag
              :type="
                row.status === 'completed'
                  ? 'success'
                  : row.status === 'failed'
                    ? 'danger'
                    : row.status === 'processing'
                      ? 'warning'
                      : 'info'
              "
              size="small"
            >
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="150">
          <template #default="{ row }">
            {{ row.processed_rows }}/{{ row.total_rows }}
          </template>
        </el-table-column>
        <el-table-column label="成功/失败" width="120">
          <template #default="{ row }">
            {{ row.success_count }}/{{ row.error_count }}
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
</style>
