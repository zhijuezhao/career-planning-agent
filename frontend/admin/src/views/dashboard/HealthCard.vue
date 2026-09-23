<script setup lang="ts">
/** 系统健康卡（P1-6）：数据库 / 调度器 / LLM 网关 三枚状态徽章 */
import { computed } from 'vue'

interface HealthData {
  database: string
  scheduler: string
  llm_gateway: string
}

const props = withDefaults(
  defineProps<{
    health: HealthData | null
    loading?: boolean
  }>(),
  { loading: false },
)

const LABELS: Record<string, string> = {
  healthy: '正常',
  unhealthy: '异常',
  running: '运行中',
  stopped: '已停止',
  not_initialized: '未初始化',
  no_models: '无可用模型',
  unknown: '未知',
}

const items = computed(() => [
  { label: '数据库', value: props.health?.database ?? 'unknown' },
  { label: '调度器', value: props.health?.scheduler ?? 'unknown' },
  { label: 'LLM 网关', value: props.health?.llm_gateway ?? 'unknown' },
])

function tagType(value: string): 'success' | 'warning' | 'danger' | 'info' {
  if (value === 'healthy' || value === 'running') return 'success'
  if (value === 'unhealthy') return 'danger'
  if (value === 'no_models' || value === 'stopped') return 'warning'
  return 'info'
}

const labelOf = (value: string) => LABELS[value] ?? value
</script>

<template>
  <el-card class="health-card" v-loading="loading">
    <template #header>
      <span class="card-title">系统健康</span>
    </template>
    <div class="health-list">
      <div v-for="item in items" :key="item.label" class="health-item">
        <span class="health-label">{{ item.label }}</span>
        <el-tag :type="tagType(item.value)" size="small" effect="light">
          {{ labelOf(item.value) }}
        </el-tag>
      </div>
    </div>
  </el-card>
</template>

<style scoped>
.health-card {
  border-radius: 12px;
  border: 1px solid #e6e6e6;
  height: 100%;
  box-sizing: border-box;
}

.card-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.health-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 4px 0;
}

.health-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.health-label {
  font-size: 13px;
  color: #606266;
}
</style>
