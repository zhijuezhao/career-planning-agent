<template>
  <div>
    <el-card>
      <div class="toolbar">
        <el-input v-model="query.industry" placeholder="行业" style="width: 150px" clearable />
        <el-input v-model="query.city" placeholder="城市" style="width: 150px" clearable />
        <el-button type="primary" @click="handleSearch">搜索</el-button>
        <el-button type="danger" :disabled="selectedIds.length === 0" @click="handleBatchDelete">批量删除</el-button>
      </div>
      <el-table v-loading="loading" :data="tableData" stripe @selection-change="handleSelectionChange">
        <el-table-column type="selection" width="50" />
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="title" label="岗位名称" />
        <el-table-column prop="company" label="公司" />
        <el-table-column prop="city" label="城市" />
        <el-table-column prop="industry" label="行业" />
        <el-table-column label="状态" prop="is_active" />
      </el-table>
      <div class="pagination">
        <el-pagination v-model:current-page="query.page" :page-size="query.limit" :total="total" layout="total, prev, pager, next" @current-change="fetchData" />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { get, post } from '@/api/request'

interface RawDataItem {
  id: number
  title: string
  company: string | null
  city: string | null
  industry: string | null
  is_active: boolean
}

const loading = ref(false)
const tableData = ref<RawDataItem[]>([])
const total = ref(0)
const selectedIds = ref<number[]>([])

const query = reactive({
  page: 1,
  limit: 20,
  industry: '',
  city: '',
})

const fetchData = async () => {
  loading.value = true
  try {
    const params: Record<string, any> = {
      skip: (query.page - 1) * query.limit,
      limit: query.limit,
    }
    if (query.industry) params.industry = query.industry
    if (query.city) params.city = query.city
    const res = await get<{ items: RawDataItem[]; total: number }>('/v1/admin/raw-data', { params })
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

const handleSelectionChange = (selection: RawDataItem[]) => {
  selectedIds.value = selection.map((item) => item.id)
}

const handleBatchDelete = async () => {
  if (selectedIds.value.length === 0) return
  try {
    await post('/v1/admin/raw-data/batch-delete', selectedIds.value)
    ElMessage.success('批量删除成功')
    fetchData()
  } catch {
    // error handled by interceptor
  }
}

onMounted(fetchData)
</script>

<style scoped>
.toolbar {
  display: flex;
  gap: 10px;
  margin-bottom: 20px;
}

.pagination {
  margin-top: 20px;
  display: flex;
  justify-content: flex-end;
}
</style>
