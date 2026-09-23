<script setup lang="ts">
/**
 * 旧版 AI 配置（只读）
 *
 * 历史遗留的 `ai_configs` 表：**不参与运行时生效**（LLM 网关只读 env 或新的
 * 供应商/模型/功能路由）。这里保留只读展示，避免"页面改版后老数据看不见"，
 * 需要修改请到「供应商 / 模型 / 功能路由」三块里操作。
 */
import { onMounted, ref, watch } from 'vue'
import { get } from '@/api/request'

interface LegacyAIConfig {
  id: number
  function_key: string
  provider: string
  model_name: string
  base_url: string | null
  temperature: number
  max_tokens: number
  is_active: boolean
}

const props = defineProps<{ reloadToken?: number }>()

const loading = ref(false)
const rows = ref<LegacyAIConfig[]>([])

const fetchData = async () => {
  loading.value = true
  try {
    const res = await get<{ items: LegacyAIConfig[]; total: number }>('/v1/admin/system/configs', {
      params: { limit: 100 },
    })
    rows.value = res.items
  } catch {
    // error handled by interceptor
  } finally {
    loading.value = false
  }
}

onMounted(fetchData)
watch(() => props.reloadToken, fetchData)
</script>

<template>
  <el-card class="data-card">
    <el-alert
      type="warning"
      :closable="false"
      show-icon
      title="这张表当前不参与生效"
      description="ai_configs 是旧版配置表；运行时用的是「供应商 / 模型 / 功能路由」。此处仅作只读留档。"
      class="hint"
    />
    <el-table v-loading="loading" :data="rows" stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="function_key" label="功能标识" width="180" />
      <el-table-column prop="provider" label="提供商" width="120" />
      <el-table-column prop="model_name" label="模型" width="180" show-overflow-tooltip />
      <el-table-column prop="base_url" label="Base URL" min-width="220" show-overflow-tooltip>
        <template #default="{ row }">{{ row.base_url || '-' }}</template>
      </el-table-column>
      <el-table-column prop="temperature" label="温度" width="80" />
      <el-table-column prop="max_tokens" label="max_tokens" width="110" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
            {{ row.is_active ? '启用' : '禁用' }}
          </el-tag>
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
</style>
