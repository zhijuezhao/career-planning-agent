<script setup lang="ts">
/** 调度器状态（原系统配置页保留块） */
import { onMounted, ref, watch } from 'vue'
import { getSchedulerStatus } from './api'

const props = defineProps<{ reloadToken?: number }>()

const status = ref('unknown')
const jobs = ref<Array<Record<string, unknown>>>([])
const loading = ref(false)

const fetchData = async () => {
  loading.value = true
  try {
    const res = await getSchedulerStatus()
    status.value = res.status
    jobs.value = res.jobs
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
  <el-card class="data-card" v-loading="loading">
    <template #header>
      <div class="card-header">
        <span>调度器状态</span>
        <div>
          <el-tag :type="status === 'running' ? 'success' : 'info'" size="small">{{ status }}</el-tag>
          <el-button size="small" class="refresh" @click="fetchData">刷新</el-button>
        </div>
      </div>
    </template>
    <div v-if="jobs.length > 0">
      <el-table :data="jobs" stripe size="small">
        <el-table-column prop="name" label="任务名称" />
        <el-table-column prop="next_run" label="下次运行" />
      </el-table>
    </div>
    <el-empty v-else description="暂无调度任务" :image-size="60" />
  </el-card>
</template>

<style scoped>
.data-card {
  border-radius: 12px;
  border: 1px solid #e6e6e6;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.refresh {
  margin-left: 10px;
}
</style>
