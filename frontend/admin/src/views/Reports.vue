<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { get, post, put, remove } from '@/api/request'

interface ReportItem {
  id: number
  user_id: number
  target_job: string | null
  version: number
  created_at: string
}

const loading = ref(false)
const tableData = ref<ReportItem[]>([])
const total = ref(0)

const query = reactive({
  page: 1,
  limit: 20,
  user_id: undefined as number | undefined,
})

const fetchData = async () => {
  loading.value = true
  try {
    const params: Record<string, any> = {
      skip: (query.page - 1) * query.limit,
      limit: query.limit,
    }
    if (query.user_id) params.user_id = query.user_id
    const res = await get<{ items: ReportItem[]; total: number }>('/v1/admin/reports', { params })
    tableData.value = res.items
    total.value = res.total
  } catch {
    // error handled by interceptor
  } finally {
    loading.value = false
  }
}

const handleSearch = () => {
  query.page = 1
  fetchData()
}

const handleDownload = (row: ReportItem) => {
  const token = localStorage.getItem('token')
  window.open(`/api/v1/admin/reports/${row.id}/download?token=${token}`, '_blank')
}

const handleDelete = async (row: ReportItem) => {
  try {
    await remove(`/v1/admin/reports/${row.id}`)
    ElMessage.success('删除成功')
    fetchData()
  } catch {
    // error handled by interceptor
  }
}

onMounted(fetchData)
</script>

<template>
  <div>
    <el-card class="data-card">
      <div class="toolbar">
        <el-input
          v-model.number="query.user_id"
          placeholder="用户ID"
          style="width: 150px"
          clearable
        />
        <el-button type="primary" @click="handleSearch">搜索</el-button>
      </div>

      <el-table v-loading="loading" :data="tableData" stripe>
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="user_id" label="用户ID" width="100" />
        <el-table-column prop="target_job" label="目标岗位" />
        <el-table-column label="版本" width="80">
          <template #default="{ row }">
            <el-tag size="small">v{{ row.version }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }">
            {{ new Date(row.created_at).toLocaleString() }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <el-button type="primary" size="small" @click="handleDownload(row)">
              下载
            </el-button>
            <el-button type="danger" size="small" @click="handleDelete(row)">
              删除
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
  </div>
</template>

<style scoped>
.data-card {
  border-radius: 12px;
  border: 1px solid #e6e6e6;
}

.toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}
</style>
