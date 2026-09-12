<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { get, post, put, remove } from '@/api/request'

interface AIConfig {
  id: number
  function_key: string
  provider: string
  model_name: string
  temperature: number
  max_tokens: number
  is_active: boolean
}

const loading = ref(false)
const tableData = ref<AIConfig[]>([])
const total = ref(0)
const dialogVisible = ref(false)
const formRef = ref<FormInstance>()

const query = reactive({
  page: 1,
  limit: 20,
})

const form = reactive({
  function_key: '',
  provider: '',
  model_name: '',
  temperature: 0.7,
  max_tokens: 4096,
})

const rules: FormRules = {
  function_key: [{ required: true, message: '请输入功能标识', trigger: 'blur' }],
  provider: [{ required: true, message: '请输入提供商', trigger: 'blur' }],
  model_name: [{ required: true, message: '请输入模型名称', trigger: 'blur' }],
}

const schedulerStatus = ref({
  status: 'unknown',
  jobs: [] as any[],
})

const fetchData = async () => {
  loading.value = true
  try {
    const res = await get<{ items: AIConfig[]; total: number }>('/v1/admin/system/configs', {
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

const fetchSchedulerStatus = async () => {
  try {
    schedulerStatus.value = await get('/v1/admin/system/scheduler/status')
  } catch {
    // error handled by interceptor
  }
}

const handleCreate = () => {
  form.function_key = ''
  form.provider = ''
  form.model_name = ''
  form.temperature = 0.7
  form.max_tokens = 4096
  dialogVisible.value = true
}

const handleDelete = async (row: AIConfig) => {
  try {
    await remove(`/v1/admin/system/configs/${row.id}`)
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
      await post('/v1/admin/system/configs', form)
      ElMessage.success('创建成功')
      dialogVisible.value = false
      fetchData()
    } catch {
      // error handled by interceptor
    }
  })
}

onMounted(() => {
  fetchData()
  fetchSchedulerStatus()
})
</script>

<template>
  <div>
    <el-card class="scheduler-card data-card">
      <template #header>
        <div class="card-header">
          <span>调度器状态</span>
          <el-tag :type="schedulerStatus.status === 'running' ? 'success' : 'info'" size="small">
            {{ schedulerStatus.status }}
          </el-tag>
        </div>
      </template>
      <div v-if="schedulerStatus.jobs.length > 0">
        <el-table :data="schedulerStatus.jobs" stripe size="small">
          <el-table-column prop="name" label="任务名称" />
          <el-table-column prop="next_run" label="下次运行" />
        </el-table>
      </div>
      <el-empty v-else description="暂无调度任务" :image-size="60" />
    </el-card>

    <el-card class="config-card data-card">
      <template #header>
        <div class="card-header">
          <span>AI 配置</span>
          <el-button type="primary" size="small" @click="handleCreate">新建</el-button>
        </div>
      </template>

      <el-table v-loading="loading" :data="tableData" stripe>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="function_key" label="功能标识" width="150" />
        <el-table-column prop="provider" label="提供商" width="100" />
        <el-table-column prop="model_name" label="模型" width="150" />
        <el-table-column prop="temperature" label="温度" width="80" />
        <el-table-column prop="max_tokens" label="最大Token" width="100" />
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
              {{ row.is_active ? '启用' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button type="danger" size="small" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" title="新建配置" width="500px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
        <el-form-item label="功能标识" prop="function_key">
          <el-input v-model="form.function_key" placeholder="如：resume_parser" />
        </el-form-item>
        <el-form-item label="提供商" prop="provider">
          <el-input v-model="form.provider" placeholder="如：deepseek" />
        </el-form-item>
        <el-form-item label="模型" prop="model_name">
          <el-input v-model="form.model_name" placeholder="如：deepseek-chat" />
        </el-form-item>
        <el-form-item label="温度">
          <el-input-number v-model="form.temperature" :min="0" :max="2" :step="0.1" />
        </el-form-item>
        <el-form-item label="最大Token">
          <el-input-number v-model="form.max_tokens" :min="1" :max="100000" :step="1000" />
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
.data-card {
  border-radius: 12px;
  border: 1px solid #e6e6e6;
}

.scheduler-card {
  margin-bottom: 20px;
}

.config-card {
  margin-top: 20px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
