<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  Briefcase,
  ChatDotRound,
  Connection,
  Document,
  DocumentChecked,
  User,
} from '@element-plus/icons-vue'
import { get, post, put, remove } from '@/api/request'

const stats = ref({
  total_users: 0,
  total_resumes: 0,
  total_job_profiles: 0,
  total_matches: 0,
  total_reports: 0,
  total_chat_sessions: 0,
})

const statCards = [
  { key: 'total_users', label: '用户总数', icon: User, color: 'blue' },
  { key: 'total_resumes', label: '简历总数', icon: Document, color: 'green' },
  { key: 'total_job_profiles', label: '岗位画像', icon: Briefcase, color: 'orange' },
  { key: 'total_matches', label: '匹配次数', icon: Connection, color: 'purple' },
  { key: 'total_reports', label: '报告数量', icon: DocumentChecked, color: 'cyan' },
  { key: 'total_chat_sessions', label: '对话会话', icon: ChatDotRound, color: 'pink' },
]

const fetchStats = async () => {
  try {
    const res = await get<{
      total_users: number
      total_resumes: number
      total_job_profiles: number
      total_matches: number
      total_reports: number
      total_chat_sessions: number
    }>('/v1/admin/dashboard/overview')
    stats.value = res
  } catch {
    // error handled by interceptor
  }
}

onMounted(fetchStats)
</script>

<template>
  <div class="dashboard">
    <div class="stat-cards">
      <div v-for="card in statCards" :key="card.key" class="stat-card">
        <div class="stat-icon" :class="card.color">
          <el-icon><component :is="card.icon" /></el-icon>
        </div>
        <div class="stat-value">{{ stats[card.key as keyof typeof stats] || 0 }}</div>
        <div class="stat-label">{{ card.label }}</div>
      </div>
    </div>

    <el-card class="info-card">
      <template #header>
        <span>系统概览</span>
      </template>
      <el-empty description="更多数据图表开发中..." />
    </el-card>
  </div>
</template>

<style scoped>
.stat-cards {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}

.stat-card {
  background: #fff;
  border-radius: 12px;
  padding: 20px;
  border: 1px solid #e6e6e6;
  transition: all 0.2s;
}

.stat-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  transform: translateY(-2px);
}

.stat-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  margin-bottom: 12px;
}

.stat-icon.blue {
  background: #eef2ff;
  color: #667eea;
}

.stat-icon.green {
  background: #f0fdf4;
  color: #22c55e;
}

.stat-icon.orange {
  background: #fff7ed;
  color: #f97316;
}

.stat-icon.purple {
  background: #faf5ff;
  color: #a855f7;
}

.stat-icon.cyan {
  background: #ecfeff;
  color: #06b6d4;
}

.stat-icon.pink {
  background: #fdf2f8;
  color: #ec4899;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: #1f2937;
}

.stat-label {
  margin-top: 4px;
  font-size: 13px;
  color: #909399;
}

.info-card {
  border-radius: 12px;
  border: 1px solid #e6e6e6;
}
</style>
