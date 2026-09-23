<script setup lang="ts">
/**
 * 模型管理（B2-1）
 *
 * - 模型挂在供应商下：`kind=chat` 进 LLM 网关，`kind=embedding` 供向量客户端使用。
 * - 「测试」是真实调用：chat 发最小 ping，embedding 取一次向量并核对维度
 *   （DB 向量列固定 vector(1024)，不一致会以红色失败原因直接给出）。
 * - 温度 / max_tokens 留空 = 用全局默认（env llm_temperature / llm_max_tokens）。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import {
  createModel,
  deleteModel,
  listModels,
  listProviders,
  testModel,
  updateModel,
  type ConnectivityResult,
  type LLMModel,
  type LLMProvider,
  type ModelPayload,
} from './api'

const props = defineProps<{ reloadToken?: number }>()

const loading = ref(false)
const rows = ref<LLMModel[]>([])
const providers = ref<LLMProvider[]>([])
const filterProvider = ref<number | undefined>(undefined)
const filterKind = ref<'' | 'chat' | 'embedding'>('')

const dialogVisible = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)
const formRef = ref<FormInstance>()

const form = reactive({
  provider_id: undefined as number | undefined,
  model_name: '',
  display_name: '',
  kind: 'chat' as 'chat' | 'embedding',
  dim: 1024 as number | null,
  temperature: null as number | null,
  max_tokens: null as number | null,
  enabled: true,
})

const rules: FormRules = {
  provider_id: [{ required: true, message: '请选择供应商', trigger: 'change' }],
  model_name: [{ required: true, message: '请输入模型名（供应商下唯一）', trigger: 'blur' }],
}

const testVisible = ref(false)
const testingId = ref<number | null>(null)
const testResult = ref<ConnectivityResult | null>(null)

const chatCount = computed(() => rows.value.filter((r) => r.kind === 'chat').length)
const embedCount = computed(() => rows.value.filter((r) => r.kind === 'embedding').length)

const fetchProviders = async () => {
  try {
    providers.value = (await listProviders()).items
  } catch {
    // error handled by interceptor
  }
}

const fetchData = async () => {
  loading.value = true
  try {
    const params: { provider_id?: number; kind?: string } = {}
    if (filterProvider.value) params.provider_id = filterProvider.value
    if (filterKind.value) params.kind = filterKind.value
    rows.value = (await listModels(params)).items
  } catch {
    // error handled by interceptor
  } finally {
    loading.value = false
  }
}

const openCreate = () => {
  editingId.value = null
  form.provider_id = filterProvider.value ?? providers.value[0]?.id
  form.model_name = ''
  form.display_name = ''
  form.kind = 'chat'
  form.dim = 1024
  form.temperature = null
  form.max_tokens = null
  form.enabled = true
  dialogVisible.value = true
}

const openEdit = (row: LLMModel) => {
  editingId.value = row.id
  form.provider_id = row.provider_id
  form.model_name = row.model_name
  form.display_name = row.display_name ?? ''
  form.kind = row.kind
  form.dim = row.dim
  form.temperature = row.temperature
  form.max_tokens = row.max_tokens
  form.enabled = row.enabled
  dialogVisible.value = true
}

const submit = async () => {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    saving.value = true
    try {
      const payload: ModelPayload = {
        model_name: form.model_name,
        display_name: form.display_name || null,
        kind: form.kind,
        dim: form.kind === 'embedding' ? form.dim : null,
        temperature: form.temperature,
        max_tokens: form.max_tokens,
        enabled: form.enabled,
      }
      if (editingId.value === null) {
        payload.provider_id = form.provider_id
        await createModel(payload)
        ElMessage.success('已创建（立即生效）')
      } else {
        await updateModel(editingId.value, payload)
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

const toggleEnabled = async (row: LLMModel) => {
  try {
    await updateModel(row.id, { enabled: row.enabled })
    ElMessage.success(row.enabled ? '已启用' : '已禁用（相关功能路由自动回退）')
  } catch {
    row.enabled = !row.enabled
  }
}

const handleTest = async (row: LLMModel) => {
  testingId.value = row.id
  try {
    const res = await testModel(row.id)
    testResult.value = res
    testVisible.value = true
    if (res.ok) ElMessage.success(`连通正常 · ${res.latency_ms} ms`)
  } catch {
    // error handled by interceptor
  } finally {
    testingId.value = null
  }
}

const handleDelete = async (row: LLMModel) => {
  try {
    await ElMessageBox.confirm(
      `删除模型「${row.model_name}」会同时删除绑定它的功能路由，且不可撤销。`,
      '删除确认',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  try {
    await deleteModel(row.id)
    ElMessage.success('已删除')
    await fetchData()
  } catch {
    // error handled by interceptor
  }
}

onMounted(async () => {
  await fetchProviders()
  await fetchData()
})
watch(() => props.reloadToken, async () => {
  await fetchProviders()
  await fetchData()
})
</script>

<template>
  <el-card class="data-card">
    <el-alert
      type="info"
      :closable="false"
      show-icon
      :title="`共 ${rows.length} 个模型（对话 ${chatCount} / 向量 ${embedCount}）`"
      description="对话模型可直接被「功能路由」绑定；向量模型只能绑定 embedding 功能键，维度需与 DB 的 vector(1024) 一致。"
      class="hint"
    />

    <div class="toolbar">
      <el-select
        v-model="filterProvider"
        placeholder="全部供应商"
        clearable
        style="width: 200px"
        @change="fetchData"
      >
        <el-option v-for="p in providers" :key="p.id" :label="p.name" :value="p.id" />
      </el-select>
      <el-select v-model="filterKind" placeholder="全部类型" style="width: 140px" @change="fetchData">
        <el-option label="全部类型" value="" />
        <el-option label="对话 chat" value="chat" />
        <el-option label="向量 embedding" value="embedding" />
      </el-select>
      <el-button type="primary" @click="openCreate">新建模型</el-button>
      <el-button @click="fetchData">刷新</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="provider_name" label="供应商" width="150" show-overflow-tooltip />
      <el-table-column prop="model_name" label="模型名" min-width="180" show-overflow-tooltip />
      <el-table-column prop="display_name" label="显示名" width="140" show-overflow-tooltip>
        <template #default="{ row }">{{ row.display_name || '-' }}</template>
      </el-table-column>
      <el-table-column label="类型" width="110">
        <template #default="{ row }">
          <el-tag size="small" :type="row.kind === 'embedding' ? 'warning' : 'primary'">
            {{ row.kind === 'embedding' ? '向量' : '对话' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="维度" width="90">
        <template #default="{ row }">{{ row.dim ?? '-' }}</template>
      </el-table-column>
      <el-table-column label="温度" width="80">
        <template #default="{ row }">{{ row.temperature ?? '默认' }}</template>
      </el-table-column>
      <el-table-column label="max_tokens" width="110">
        <template #default="{ row }">{{ row.max_tokens ?? '默认' }}</template>
      </el-table-column>
      <el-table-column label="启用" width="90">
        <template #default="{ row }">
          <el-switch v-model="row.enabled" size="small" @change="toggleEnabled(row)" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="190" fixed="right">
        <template #default="{ row }">
          <el-button
            type="success"
            size="small"
            link
            :loading="testingId === row.id"
            @click="handleTest(row)"
          >
            测试
          </el-button>
          <el-button type="primary" size="small" link @click="openEdit(row)">编辑</el-button>
          <el-button type="danger" size="small" link @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId === null ? '新建模型' : '编辑模型'"
      width="600px"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="110px">
        <el-form-item label="供应商" prop="provider_id">
          <el-select v-model="form.provider_id" :disabled="editingId !== null" style="width: 100%">
            <el-option v-for="p in providers" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="模型名" prop="model_name">
          <el-input v-model="form.model_name" placeholder="如：deepseek-chat / Qwen/Qwen3-Embedding-8B" />
        </el-form-item>
        <el-form-item label="显示名">
          <el-input v-model="form.display_name" placeholder="仅用于界面展示，可留空" />
        </el-form-item>
        <el-form-item label="类型">
          <el-radio-group v-model="form.kind">
            <el-radio-button value="chat">对话 chat</el-radio-button>
            <el-radio-button value="embedding">向量 embedding</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.kind === 'embedding'" label="维度 dim">
          <el-input-number v-model="form.dim" :min="1" :max="65536" />
          <span class="tip">DB 向量列固定 1024，填别的值测试会报错</span>
        </el-form-item>
        <el-form-item v-if="form.kind === 'chat'" label="温度">
          <el-input-number v-model="form.temperature" :min="0" :max="2" :step="0.1" />
          <span class="tip">留空用全局默认</span>
        </el-form-item>
        <el-form-item v-if="form.kind === 'chat'" label="max_tokens">
          <el-input-number v-model="form.max_tokens" :min="1" :max="100000" :step="512" />
          <span class="tip">留空用全局默认</span>
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

    <el-dialog v-model="testVisible" title="连通性测试结果" width="600px">
      <el-descriptions v-if="testResult" :column="1" border size="small">
        <el-descriptions-item label="结果">
          <el-tag :type="testResult.ok ? 'success' : 'danger'" size="small">
            {{ testResult.ok ? '正常' : '失败' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="模型">
          {{ testResult.model }}（{{ testResult.kind === 'embedding' ? '向量' : '对话' }}）
        </el-descriptions-item>
        <el-descriptions-item label="耗时">{{ testResult.latency_ms }} ms</el-descriptions-item>
        <el-descriptions-item v-if="testResult.dim !== null" label="维度">
          {{ testResult.dim }}（期望 {{ testResult.dim_expected }}）
        </el-descriptions-item>
        <el-descriptions-item label="说明">{{ testResult.detail }}</el-descriptions-item>
        <el-descriptions-item v-if="testResult.output_preview" label="返回片段">
          {{ testResult.output_preview }}
        </el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <el-button type="primary" @click="testVisible = false">知道了</el-button>
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
