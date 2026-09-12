<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { get, post, put, remove } from '@/api/request'

interface UserItem {
  id: number
  username: string
  email: string | null
  phone: string | null
  role: string
  status: number
  created_at: string
}

const loading = ref(false)
const tableData = ref<UserItem[]>([])
const total = ref(0)

const query = reactive({
  page: 1,
  limit: 20,
  keyword: '',
  role: '',
  status: undefined as number | undefined,
})

const fetchData = async () => {
  loading.value = true
  try {
    const params: Record<string, any> = {
      skip: (query.page - 1) * query.limit,
      limit: query.limit,
    }
    if (query.keyword) params.keyword = query.keyword
    if (query.role) params.role = query.role
    if (query.status !== undefined) params.status = query.status
    const res = await get<{ items: UserItem[]; total: number }>('/v1/admin/users', { params })
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

const handleDelete = async (row: UserItem) => {
  try {
    await remove(`/v1/admin/users/${row.id}`)
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
    <el-card>
      <div class="toolbar">
        <el-input v-model="query.keyword" placeholder="用户名/邮箱" style="width: 200px" clearable />
        <el-select v-model="query.role" placeholder="角色" clearable style="width: 120px">
          <el-option label="学生" value="student" />
          <el-option label="管理员" value="admin" />
        </el-select>
        <el-button type="primary" @click="handleSearch">搜索</el-button>
      </div>

      <el-table v-loading="loading" :data="tableData" stripe>
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="username" label="用户名" />
        <el-table-column prop="email" label="邮箱" />
        <el-table-column prop="phone" label="手机号" width="130" />
        <el-table-column label="角色" width="100">
          <template #default="{ row }">
            <el-tag :type="row.role === 'admin' ? 'danger' : ''">{{ row.role }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.status === 1 ? 'success' : 'info'">
              {{ row.status === 1 ? '启用' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150">
          <template #default="{ row }">
            <el-button type="danger" size="small" @click="handleDelete(row)">删除</el-button>
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
.toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}
</style>
