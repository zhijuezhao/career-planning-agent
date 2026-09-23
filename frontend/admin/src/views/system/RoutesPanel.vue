<script setup lang="ts">
/**
 * 功能路由（B2-1）
 *
 * 把「功能键」绑定到具体模型，是模型配置中心真正起作用的一环：
 * - 后端每个功能键都有明确的调用点（如 `job_quality` = 导入质检），绑定后下一次调用即生效；
 * - 未绑定 / 绑定失效（模型或供应商被禁用、kind 不符、供应商无密钥）→ 自动回退 env 默认；
 * - 「当前生效」列展示的就是**运行时真实结果**，与后端注册表快照判断规则一致。
 */
import { onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { bindRoute, listModels, listRoutes, type FunctionRoute, type LLMModel } from './api'

const props = defineProps<{ reloadToken?: number }>()

const loading = ref(false)
const rows = ref<FunctionRoute[]>([])
const models = ref<LLMModel[]>([])
const draft = reactive<Record<string, number | null>>({})
const savingKey = ref<string | null>(null)

const optionsFor = (kind: string) => models.value.filter((m) => m.kind === kind && m.enabled)

const labelOf = (model: LLMModel) =>
  `${model.provider_name ?? model.provider_id}:${model.model_name}`

const fetchData = async () => {
  loading.value = true
  try {
    const [routeRes, modelRes] = await Promise.all([listRoutes(), listModels()])
    rows.value = routeRes.items
    models.value = modelRes.items
    for (const item of rows.value) draft[item.function_key] = item.bound_model_id
  } catch {
    // error handled by interceptor
  } finally {
    loading.value = false
  }
}

const isDirty = (row: FunctionRoute) =>
  (draft[row.function_key] ?? null) !== (row.bound_model_id ?? null)

const save = async (row: FunctionRoute) => {
  savingKey.value = row.function_key
  try {
    const modelId = draft[row.function_key] ?? null
    const res = await bindRoute(row.function_key, modelId)
    if (res.warning) {
      ElMessage.warning(`已保存：${res.warning}`)
    } else if (res.source === 'db') {
      ElMessage.success(`已生效：${res.effective}`)
    } else if (modelId === null) {
      ElMessage.success('已解绑，回退 env 默认')
    } else {
      ElMessage.warning('已绑定但尚未生效，请检查供应商密钥/模型状态')
    }
    await fetchData()
  } catch {
    // error handled by interceptor
  } finally {
    savingKey.value = null
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
      title="绑定后立即生效，不需要重启后端"
      description="未绑定或绑定失效时自动回退 env 默认（简历解析额外回退 env RESUME_LLM_MODEL）；把下拉清空再保存即为解绑。标「待接入」的功能键调用点还没接，绑了暂不生效。"
      class="hint"
    />

    <div class="toolbar">
      <el-button @click="fetchData">刷新</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" stripe>
      <el-table-column label="功能键" width="240">
        <template #default="{ row }">
          <div class="key-cell">
            <code>{{ row.function_key }}</code>
            <span class="label">{{ row.label }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="row.kind === 'embedding' ? 'warning' : 'primary'">
            {{ row.kind === 'embedding' ? '向量' : '对话' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="调用点" width="110">
        <template #default="{ row }">
          <el-tag v-if="row.wired" size="small" type="success">已接入</el-tag>
          <el-tooltip v-else content="调用点尚未接入（B3-2 链接解析才用到），绑定后暂不生效" placement="top">
            <el-tag size="small" type="info">待接入</el-tag>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column label="绑定模型" min-width="260">
        <template #default="{ row }">
          <el-select
            v-model="draft[row.function_key]"
            clearable
            placeholder="未绑定（回退 env）"
            style="width: 100%"
          >
            <el-option
              v-for="m in optionsFor(row.kind)"
              :key="m.id"
              :label="labelOf(m)"
              :value="m.id"
            />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column label="当前生效" min-width="240">
        <template #default="{ row }">
          <div class="effective-cell">
            <el-tag :type="row.source === 'db' ? 'success' : 'info'" size="small">
              {{ row.source === 'db' ? 'DB' : 'env' }}
            </el-tag>
            <span class="effective">{{ row.effective }}</span>
          </div>
          <div v-if="row.warning" class="warning">{{ row.warning }}</div>
        </template>
      </el-table-column>
      <el-table-column label="回退" width="200" show-overflow-tooltip>
        <template #default="{ row }">{{ row.fallback }}</template>
      </el-table-column>
      <el-table-column label="操作" width="110" fixed="right">
        <template #default="{ row }">
          <el-button
            type="primary"
            size="small"
            :disabled="!isDirty(row)"
            :loading="savingKey === row.function_key"
            @click="save(row)"
          >
            保存
          </el-button>
        </template>
      </el-table-column>
    </el-table>
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

.key-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.key-cell code {
  font-family: 'JetBrains Mono', Consolas, Monaco, monospace;
  font-size: 13px;
  color: #409eff;
}

.key-cell .label {
  font-size: 12px;
  color: #909399;
}

.effective-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.effective {
  font-size: 13px;
  word-break: break-all;
}

.warning {
  margin-top: 4px;
  font-size: 12px;
  color: #e6a23c;
}
</style>
