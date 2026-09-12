<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { get, post, put, remove } from '@/api/request'

interface CareerPath {
  id: number
  user_id: number
  target_position: string | null
  path_type: string | null
  created_at: string
}

interface GrowthPlan {
  id: number
  user_id: number
  growth_path_id: number
  cycle_weeks: number | null
  intensity: string | null
  created_at: string
}

const loading = ref(false)
const pathData = ref<CareerPath[]>([])
const planData = ref<GrowthPlan[]>([])
const pathTotal = ref(0)
const planTotal = ref(0)
const activeTab = ref('paths')

const query = reactive({
  page: 1,
  limit: 20,
})

const fetchPaths = async () => {
  loading.value = true
  try {
    const res = await get<{ items: CareerPath[]; total: number }>('/v1/admin/career/paths', {
      params: { skip: (query.page - 1) * query.limit, limit: query.limit },
    })
    pathData.value = res.items
    pathTotal.value = res.total
  } catch {
    // error handled by interceptor
  } finally {
    loading.value = false
  }
}

const fetchPlans = async () => {
  loading.value = true
  try {
    const res = await get<{ items: GrowthPlan[]; total: number }>('/v1/admin/career/plans', {
      params: { skip: (query.page - 1) * query.limit, limit: query.limit },
    })
    planData.value = res.items
    planTotal.value = res.total
  } catch {
    // error handled by interceptor
  } finally {
    loading.value = false
  }
}

const handleTabChange = (tab: string) => {
  query.page = 1
  if (tab === 'paths') fetchPaths()
  else if (tab === 'plans') fetchPlans()
}

onMounted(fetchPaths)
</script>

<template>
  <div>
    <el-card class="data-card">
      <el-tabs v-model="activeTab" @tab-change="handleTabChange">
        <el-tab-pane label="职业路线" name="paths">
          <el-table v-loading="loading" :data="pathData" stripe>
            <el-table-column prop="id" label="ID" width="80" />
            <el-table-column prop="user_id" label="用户ID" width="100" />
            <el-table-column prop="target_position" label="目标岗位" />
            <el-table-column label="路线类型" width="120">
              <template #default="{ row }">
                <el-tag size="small">{{ row.path_type || '-' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="创建时间" width="180">
              <template #default="{ row }">
                {{ new Date(row.created_at).toLocaleString() }}
              </template>
            </el-table-column>
          </el-table>
          <el-pagination
            v-model:current-page="query.page"
            :page-size="query.limit"
            :total="pathTotal"
            layout="total, prev, pager, next"
            @current-change="fetchPaths"
          />
        </el-tab-pane>

        <el-tab-pane label="成长计划" name="plans">
          <el-table v-loading="loading" :data="planData" stripe>
            <el-table-column prop="id" label="ID" width="80" />
            <el-table-column prop="user_id" label="用户ID" width="100" />
            <el-table-column prop="growth_path_id" label="路线ID" width="100" />
            <el-table-column label="周期" width="100">
              <template #default="{ row }">
                {{ row.cycle_weeks ? `${row.cycle_weeks}周` : '-' }}
              </template>
            </el-table-column>
            <el-table-column label="强度" width="100">
              <template #default="{ row }">
                <el-tag :type="row.intensity === 'high' ? 'danger' : row.intensity === 'medium' ? 'warning' : 'info'" size="small">
                  {{ row.intensity || '-' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="创建时间" width="180">
              <template #default="{ row }">
                {{ new Date(row.created_at).toLocaleString() }}
              </template>
            </el-table-column>
          </el-table>
          <el-pagination
            v-model:current-page="query.page"
            :page-size="query.limit"
            :total="planTotal"
            layout="total, prev, pager, next"
            @current-change="fetchPlans"
          />
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<style scoped>
.data-card {
  border-radius: 12px;
  border: 1px solid #e6e6e6;
}
</style>
