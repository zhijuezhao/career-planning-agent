<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import type { ComponentSize } from 'element-plus'
import { get, post, put, remove } from '@/api/request'

interface JobItem {
  id: number
  title: string
  industry: string | null
  level: string | null
  salary_range: string | null
  created_at: string
}

const loading = ref(false)
const tableData = ref<JobItem[]>([])
const total = ref(0)
const dialogVisible = ref(false)
const formRef = ref<FormInstance>()
const size: ComponentSize = 'default'

const query = reactive({
  page: 1,
  limit: 20,
  industry: '',
  level: '',
})

const form = reactive({
  title: '',
  industry: '',
  level: '',
  salary_range: '',
})

const rules: FormRules = {
  title: [{ required: true, message: '请输入岗位名称', trigger: 'blur' }],
}

const fetchData = async () => {
  loading.value = true
  try {
    const params: Record<string, any> = {
      skip: (query.page - 1) * query.limit,
      limit: query.limit,
    }
    if (query.industry) params.industry = query.industry
    if (query.level) params.level = query.level
    const res = await get<{ items: JobItem[]; total: number }>('/v1/admin/jobs', { params })
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

const handleCreate = () => {
  form.title = ''
  form.industry = ''
  form.level = ''
  form.salary_range = ''
  dialogVisible.value = true
}

const handleDelete = async (row: JobItem) => {
  try {
    await remove(`/v1/admin/jobs/${row.id}`)
    ElMessage.success('删除成功')
    fetchData()
  } catch {
    // error handled by interceptor
  }
}

const handleSubmit = async () => {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    try {
      await post('/v1/admin/jobs', form)
      ElMessage.success('创建成功')
      dialogVisible.value = false
      fetchData()
    } catch {
      // error handled by interceptor
    }
  })
}

onMounted(fetchData)
</script>

<template>
  <div>
    <el-card>
      <div class="toolbar">
        <el-input
          v-model="query.industry"
          placeholder="行业"
          style="width: 150px"
          clearable
        />
        <el-input
          v-model="query.level"
          placeholder="级别"
          style="width: 150px"
          clearable
        />
        <el-button type="primary" @click="handleSearch">搜索</el-button>
        <el-button type="success" @click="handleCreate">新建</el-button>
      </div>

      <el-table v-loading="loading" :data="tableData" stripe>
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="title" label="岗位名称" />
        <el-table-column prop="industry" label="行业" width="120" />
        <el-table-column prop="level" label="级别" width="100" />
        <el-table-column prop="salary_range" label="薪资" width="150" />
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

    <el-dialog v-model="dialogVisible" title="新建岗位" width="500px">
      <el-form ref="formRef" :model="form" :rules="rules" :size="size" label-width="80px">
        <el-form-item label="岗位名称" prop="title">
          <el-input v-model="form.title" />
        </el-form-item>
        <el-form-item label="行业">
          <el-input v-model="form.industry" />
        </el-form-item>
        <el-form-item label="级别">
          <el-select v-model="form.level" placeholder="请选择">
            <el-option label="初级" value="初级" />
            <el-option label="中级" value="中级" />
            <el-option label="高级" value="高级" />
          </el-select>
        </el-form-item>
        <el-form-item label="薪资">
          <el-input v-model="form.salary_range" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}
</style>
