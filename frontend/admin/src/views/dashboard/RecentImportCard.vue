<script setup lang="ts">
/** 最近导入卡（P1-6）：最近 5 条导入任务 + 状态 tag */
import { formatDateTime } from '@/utils/preview'

interface ImportJob {
  id: number
  file_name: string
  status: string
  total_rows: number
  success_count: number
  error_count: number
  created_at: string
}

withDefaults(
  defineProps<{
    items: ImportJob[]
    loading?: boolean
  }>(),
  { loading: false },
)

const STATUS: Record<string, { label: string; type: 'success' | 'danger' | 'warning' | 'info' }> = {
  pending: { label: '待处理', type: 'info' },
  processing: { label: '处理中', type: 'warning' },
  completed: { label: '成功', type: 'success' },
  failed: { label: '失败', type: 'danger' },
}

const statusOf = (status: string) => STATUS[status] ?? { label: status, type: 'info' as const }
</script>

<template>
  <el-card class="recent-card" v-loading="loading">
    <template #header>
      <span class="card-title">最近导入</span>
    </template>
    <el-empty v-if="!items.length" description="暂无导入记录" :image-size="60" />
    <el-table v-else :data="items" size="small" :show-header="true">
      <el-table-column prop="file_name" label="文件" min-width="140" show-overflow-tooltip />
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="statusOf(row.status).type" size="small">
            {{ statusOf(row.status).label }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="条数" width="70">
        <template #default="{ row }">{{ row.total_rows }}</template>
      </el-table-column>
      <el-table-column label="时间" width="150">
        <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<style scoped>
.recent-card {
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
</style>
