<script setup lang="ts">
/**
 * 供应商管理（B2-1）
 *
 * - 列表只显示密钥掩码（后端永不回明文）；编辑时 api_key 留空 = 不修改，填值 = 覆盖。
 * - 保存/启停/删除后后端立即重建注册表快照并失效网关单例 → 无需重启即生效。
 * - 删除供应商会级联删除其模型与相关功能路由绑定（确认框里明示）。
 */
import { onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { formatDateTime } from '@/utils/preview'
import {
  createProvider,
  deleteProvider,
  listProviders,
  updateProvider,
  type LLMProvider,
  type ProviderPayload,
} from './api'

const props = defineProps<{ reloadToken?: number }>()

const loading = ref(false)
const rows = ref<LLMProvider[]>([])
const dialogVisible = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)
const formRef = ref<FormInstance>()

const form = reactive({
  name: '',
  base_url: '',
  api_key: '',
  enabled: true,
  sort_order: 0,
})

const rules: FormRules = {
  name: [{ required: true, message: '请输入供应商名称（唯一）', trigger: 'blur' }],
}

const fetchData = async () => {
  loading.value = true
  try {
    const res = await listProviders()
    rows.value = res.items
  } catch {
    // error handled by interceptor
  } finally {
    loading.value = false
  }
}

const openCreate = () => {
  editingId.value = null
  form.name = ''
  form.base_url = ''
  form.api_key = ''
  form.enabled = true
  form.sort_order = 0
  dialogVisible.value = true
}

const openEdit = (row: LLMProvider) => {
  editingId.value = row.id
  form.name = row.name
  form.base_url = row.base_url ?? ''
  form.api_key = ''
  form.enabled = row.enabled
  form.sort_order = row.sort_order
  dialogVisible.value = true
}

const submit = async () => {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    saving.value = true
    try {
      if (editingId.value === null) {
        await createProvider({
          name: form.name,
          base_url: form.base_url || null,
          api_key: form.api_key || null,
          enabled: form.enabled,
          sort_order: form.sort_order,
        })
        ElMessage.success('已创建（立即生效，无需重启）')
      } else {
        const payload: ProviderPayload = {
          name: form.name,
          base_url: form.base_url || null,
          enabled: form.enabled,
          sort_order: form.sort_order,
        }
        // 留空 = 不改密钥；填值 = 覆盖
        if (form.api_key) payload.api_key = form.api_key
        await updateProvider(editingId.value, payload)
        ElMessage.success('已保存（立即生效）')
      }
      dialogVisible.value = false
      await fetchData()
    } catch {
      // error handled by interceptor
    } finally {
      saving.value = false
    }
  })
}

const toggleEnabled = async (row: LLMProvider) => {
  try {
    await updateProvider(row.id, { enabled: row.enabled })
    ElMessage.success(row.enabled ? '已启用（其模型重新进入网关）' : '已禁用（其模型退出网关）')
  } catch {
    row.enabled = !row.enabled
  }
}

const handleDelete = async (row: LLMProvider) => {
  try {
    await ElMessageBox.confirm(
      `删除供应商「${row.name}」会连带删除其 ${row.model_count} 个模型与相关功能路由绑定，且不可撤销。`,
      '删除确认',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  try {
    await deleteProvider(row.id)
    ElMessage.success('已删除')
    await fetchData()
  } catch {
    // error handled by interceptor
  }
}

onMounted(fetchData)
watch(() => props.reloadToken, fetchData)
</script>

<template>
  <el-card class="data-card">
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="填 OpenAI 兼容地址即可（DeepSeek / Qwen / LongCat / SiliconFlow…）"
      description="密钥加密落库、接口只回掩码。保存后立即生效，不需要重启后端。"
      class="hint"
    />

    <div class="toolbar">
      <el-button type="primary" @click="openCreate">新建供应商</el-button>
      <el-button @click="fetchData">刷新</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="name" label="名称" width="180" show-overflow-tooltip />
      <el-table-column prop="base_url" label="Base URL" min-width="240" show-overflow-tooltip>
        <template #default="{ row }">{{ row.base_url || '-' }}</template>
      </el-table-column>
      <el-table-column label="API Key" width="140">
        <template #default="{ row }">
          <el-tag v-if="row.api_key_set" size="small" type="success">{{ row.api_key_masked }}</el-tag>
          <el-tag v-else size="small" type="danger">未配置</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="model_count" label="模型数" width="90" />
      <el-table-column prop="sort_order" label="排序" width="80" />
      <el-table-column label="启用" width="90">
        <template #default="{ row }">
          <el-switch v-model="row.enabled" size="small" @change="toggleEnabled(row)" />
        </template>
      </el-table-column>
      <el-table-column label="更新时间" width="170">
        <template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="130" fixed="right">
        <template #default="{ row }">
          <el-button type="primary" size="small" link @click="openEdit(row)">编辑</el-button>
          <el-button type="danger" size="small" link @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId === null ? '新建供应商' : '编辑供应商'"
      width="560px"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="如：deepseek / siliconflow" />
        </el-form-item>
        <el-form-item label="Base URL">
          <el-input v-model="form.base_url" placeholder="如：https://api.deepseek.com/v1" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            :placeholder="editingId === null ? 'sk-...' : '留空则不修改'"
          />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="form.sort_order" :min="0" :max="9999" />
          <span class="tip">数字小的优先（影响 fallback 顺序）</span>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<style scoped>
.data-card {
  border-radius: 12px;
  border: 1px solid #e6e6e6;
}

.hint {
  margin-bottom: 14px;
}

.toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.tip {
  margin-left: 10px;
  font-size: 12px;
  color: #909399;
}
</style>
