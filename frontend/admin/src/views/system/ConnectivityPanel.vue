<script setup lang="ts">
/**
 * 连通性测试（2026-09-26）
 *
 * 与「模型」tab 里逐行的「测试」按钮互补：这里做**汇总 + 批量**，一眼看清"模型到底通不通"：
 *   ① 顶部：**当前生效的默认模型**（chat / 导入 / 简历 / 报告都走它）+ 一键测试；
 *   ② 一键并发测试所有**已启用**模型，表格列出 状态 / 耗时 / 维度 / 说明，可单独重测。
 *
 * 说明：走的是后端 `POST /system/models/{id}/test` —— chat 发最小 ping，embedding 对短文本
 * 取向量并校验维度；**都不依赖 `default` 路由是否绑定**（绑定与否只影响"当前生效"那一行）。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  listModels,
  listRoutes,
  testModel,
  type ConnectivityResult,
  type FunctionRoute,
  type LLMModel,
} from './api'

const props = defineProps<{ reloadToken: number }>()

const loading = ref(false)
const models = ref<LLMModel[]>([])
const routes = ref<FunctionRoute[]>([])
const testingAll = ref(false)
const testingId = ref<number | null>(null)
/** 模型 id → 最近一次测试结果 */
const results = ref<Record<number, ConnectivityResult>>({})

const defaultRoute = computed(
  () => routes.value.find((r) => r.function_key === 'default') ?? null,
)
const testableModels = computed(() => models.value.filter((m) => m.enabled))
/** 当前生效的默认模型（仅当它来自 DB 绑定、且能在模型列表里找到时才能直接测） */
const effectiveDefaultModel = computed<LLMModel | null>(() => {
  const boundId = defaultRoute.value?.bound_model_id
  if (!boundId) return null
  return models.value.find((m) => m.id === boundId) ?? null
})

async function load(): Promise<void> {
  loading.value = true
  try {
    const [modelRes, routeRes] = await Promise.all([listModels(), listRoutes()])
    models.value = modelRes.items || []
    routes.value = routeRes.items || []
  } catch {
    // 错误由 request 拦截器统一提示
  } finally {
    loading.value = false
  }
}

async function runTest(model: LLMModel): Promise<void> {
  testingId.value = model.id
  try {
    const res = await testModel(model.id)
    results.value = { ...results.value, [model.id]: res }
    if (res.ok) ElMessage.success(`${res.model} 连通正常 · ${res.latency_ms} ms`)
    else ElMessage.error(`${res.model} 连接失败：${res.detail || '未知原因'}`)
  } catch {
    // 错误由 request 拦截器统一提示
  } finally {
    testingId.value = null
  }
}

async function testAll(): Promise<void> {
  if (testableModels.value.length === 0) {
    ElMessage.warning('没有已启用的模型可测')
    return
  }
  testingAll.value = true
  try {
    // 并发测试；allSettled 保证单个失败不影响其余
    const settled = await Promise.allSettled(testableModels.value.map((m) => testModel(m.id)))
    const next: Record<number, ConnectivityResult> = { ...results.value }
    settled.forEach((item, index) => {
      if (item.status === 'fulfilled') {
        next[testableModels.value[index].id] = item.value
      }
    })
    results.value = next
    const okCount = testableModels.value.filter((m) => next[m.id]?.ok).length
    ElMessage.success(`测试完成：${okCount}/${testableModels.value.length} 个模型连通正常`)
  } finally {
    testingAll.value = false
  }
}

function resultOf(row: LLMModel): ConnectivityResult | null {
  return results.value[row.id] ?? null
}

watch(() => props.reloadToken, load)
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="connectivity">
    <el-card shadow="never" class="effective-card">
      <div class="effective-row">
        <div class="effective-info">
          <div class="effective-label">当前生效的默认模型</div>
          <div class="effective-value">
            <el-tag :type="defaultRoute?.source === 'db' ? 'success' : 'info'" size="small">
              {{ defaultRoute?.source === 'db' ? 'DB 绑定' : 'env / 未绑定' }}
            </el-tag>
            <span class="model-name">{{ defaultRoute?.effective || '—' }}</span>
          </div>
          <div v-if="defaultRoute?.warning" class="effective-warn">{{ defaultRoute.warning }}</div>
          <div v-else-if="!effectiveDefaultModel" class="effective-hint">
            未绑定 <code>default</code> 路由时，导入 / 简历解析 / 报告 / 对话都不会有可用模型 ——
            请到「功能路由」把 <code>default</code> 绑到一个模型。
          </div>
        </div>
        <el-button
          type="primary"
          :loading="testingId === effectiveDefaultModel?.id"
          :disabled="!effectiveDefaultModel"
          @click="effectiveDefaultModel && runTest(effectiveDefaultModel)"
        >
          测试当前生效模型
        </el-button>
      </div>
    </el-card>

    <div class="toolbar">
      <el-button type="primary" plain :loading="testingAll" @click="testAll">
        一键测试全部启用模型
      </el-button>
      <span class="toolbar-tip">已启用 {{ testableModels.length }} 个（chat / embedding）</span>
    </div>

    <el-table :data="testableModels" stripe>
      <el-table-column label="模型" min-width="200">
        <template #default="{ row }">
          {{ row.provider_name ? `${row.provider_name}:${row.model_name}` : row.model_name }}
        </template>
      </el-table-column>
      <el-table-column label="类型" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="row.kind === 'embedding' ? 'warning' : ''">
            {{ row.kind === 'embedding' ? '向量' : '对话' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="连通状态" width="110">
        <template #default="{ row }">
          <el-tag
            v-if="resultOf(row)"
            size="small"
            :type="resultOf(row)!.ok ? 'success' : 'danger'"
          >
            {{ resultOf(row)!.ok ? '正常' : '失败' }}
          </el-tag>
          <span v-else class="muted">未测试</span>
        </template>
      </el-table-column>
      <el-table-column label="耗时" width="90">
        <template #default="{ row }">
          {{ resultOf(row) ? `${resultOf(row)!.latency_ms} ms` : '-' }}
        </template>
      </el-table-column>
      <el-table-column label="维度" width="120">
        <template #default="{ row }">
          <span v-if="resultOf(row)?.dim !== null && resultOf(row)?.dim !== undefined">
            {{ resultOf(row)!.dim }}
            <span v-if="resultOf(row)!.dim_expected" class="muted">
              / 期望 {{ resultOf(row)!.dim_expected }}
            </span>
          </span>
          <span v-else class="muted">-</span>
        </template>
      </el-table-column>
      <el-table-column label="说明 / 返回片段" min-width="240">
        <template #default="{ row }">
          <div>{{ resultOf(row)?.detail || '-' }}</div>
          <div v-if="resultOf(row)?.output_preview" class="preview">
            {{ resultOf(row)!.output_preview }}
          </div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button size="small" :loading="testingId === row.id" @click="runTest(row)">
            测试
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.connectivity {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.effective-card {
  border-left: 3px solid var(--el-color-primary);
}
.effective-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.effective-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-bottom: 6px;
}
.effective-value {
  display: flex;
  align-items: center;
  gap: 8px;
}
.model-name {
  font-weight: 600;
  font-family: var(--el-font-family-mono, monospace);
}
.effective-warn {
  margin-top: 6px;
  font-size: 13px;
  color: var(--el-color-danger);
}
.effective-hint {
  margin-top: 6px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
}
.toolbar-tip {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.muted {
  color: var(--el-text-color-placeholder);
}
.preview {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
}
</style>
