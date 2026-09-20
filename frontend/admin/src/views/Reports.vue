<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { get, remove } from '@/api/request'

interface ReportItem {
  id: number
  user_id: number
  profile_snapshot_id: number
  serial_no: string
  description: string
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
  keyword: '',
})

const fetchData = async () => {
  loading.value = true
  try {
    const params: Record<string, any> = {
      skip: (query.page - 1) * query.limit,
      limit: query.limit,
    }
    if (query.user_id) params.user_id = query.user_id
    if (query.keyword) params.keyword = query.keyword
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

/**
 * 下载 Word：后端只认 Authorization 头（原实现用 ?token= 会被 401），
 * 所以走 axios 拿 blob，再用临时 <a> 触发浏览器下载。
 */
const handleDownload = async (row: ReportItem) => {
  try {
    const blob = await get<Blob>(`/v1/admin/reports/${row.id}/download`, { responseType: 'blob' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `生涯发展报告_v${row.version}_${row.serial_no}.docx`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  } catch {
    // error handled by interceptor
  }
}

const handleDelete = async (row: ReportItem) => {
  try {
    await ElMessageBox.confirm(
      `确定删除「用户 ${row.user_id} 第 ${row.version} 版」报告？删除后不可恢复。`,
      '提示',
      { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return // 用户取消
  }
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
        <el-input
          v-model="query.keyword"
          placeholder="描述关键字"
          style="width: 200px"
          clearable
          @keyup.enter="handleSearch"
        />
        <el-button type="primary" @click="handleSearch">搜索</el-button>
      </div>

      <el-table v-loading="loading" :data="tableData" stripe>
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="user_id" label="用户ID" width="100" />
        <el-table-column label="版本" width="80">
          <template #default="{ row }">
            <el-tag size="small">v{{ row.version }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" />
        <el-table-column prop="profile_snapshot_id" label="快照ID" width="100" />
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
