<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { get } from '@/api/request'

interface Snapshot {
  id: number
  user_id: number
  profile_id: number
  serial_no: string
  description: string
  matched: boolean
  matched_at: string | null
  created_at: string
  six_dim_scores: Record<string, number>
}

interface Weight {
  id: number
  job_category: string
  top_dimension: string
  weight: number
}

const loading = ref(false)
const snapshotData = ref<Snapshot[]>([])
const weightData = ref<Weight[]>([])
const snapshotTotal = ref(0)
const weightTotal = ref(0)
const activeTab = ref('snapshots')

const query = reactive({
  page: 1,
  limit: 20,
  user_id: undefined as number | undefined,
  matched: '' as '' | 'true' | 'false',
})

/** 六维分数摘要（形如：技能 4.2 · 实践 3.8 ...） */
const dimSummary = (scores: Record<string, number>) =>
  Object.entries(scores || {})
    .map(([k, v]) => `${k} ${Number(v).toFixed(1)}`)
    .join(' · ')

const fetchSnapshots = async () => {
  loading.value = true
  try {
    const params: Record<string, any> = {
      skip: (query.page - 1) * query.limit,
      limit: query.limit,
    }
    if (query.user_id) params.user_id = query.user_id
    if (query.matched !== '') params.matched = query.matched
    const res = await get<{ items: Snapshot[]; total: number }>('/v1/admin/matching/snapshots', {
      params,
    })
    snapshotData.value = res.items
    snapshotTotal.value = res.total
  } catch {
    // error handled by interceptor
  } finally {
    loading.value = false
  }
}

const fetchWeights = async () => {
  loading.value = true
  try {
    const res = await get<{ items: Weight[]; total: number }>('/v1/admin/matching/weights', {
      params: { skip: (query.page - 1) * query.limit, limit: query.limit },
    })
    weightData.value = res.items
    weightTotal.value = res.total
  } catch {
    // error handled by interceptor
  } finally {
    loading.value = false
  }
}

const handleSearch = () => {
  query.page = 1
  fetchSnapshots()
}

const handleTabChange = (tab: string) => {
  query.page = 1
  if (tab === 'snapshots') fetchSnapshots()
  else if (tab === 'weights') fetchWeights()
}

onMounted(fetchSnapshots)
</script>

<template>
  <div>
    <el-card class="data-card">
      <el-tabs v-model="activeTab" @tab-change="handleTabChange">
        <el-tab-pane label="画像快照" name="snapshots">
          <div class="toolbar">
            <el-input
              v-model.number="query.user_id"
              placeholder="用户ID"
              style="width: 150px"
              clearable
            />
            <el-select v-model="query.matched" placeholder="匹配状态" style="width: 140px">
              <el-option label="全部" value="" />
              <el-option label="已匹配" value="true" />
              <el-option label="待匹配" value="false" />
            </el-select>
            <el-button type="primary" @click="handleSearch">搜索</el-button>
          </div>

          <el-table v-loading="loading" :data="snapshotData" stripe>
            <el-table-column prop="id" label="快照ID" width="90" />
            <el-table-column prop="user_id" label="用户ID" width="100" />
            <el-table-column label="匹配状态" width="110">
              <template #default="{ row }">
                <el-tag :type="row.matched ? 'success' : 'info'" size="small">
                  {{ row.matched ? '已匹配' : '待匹配' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="六维分数" min-width="320" show-overflow-tooltip>
              <template #default="{ row }">{{ dimSummary(row.six_dim_scores) || '-' }}</template>
            </el-table-column>
            <el-table-column prop="description" label="描述" width="120" />
            <el-table-column label="创建时间" width="180">
              <template #default="{ row }">
                {{ new Date(row.created_at).toLocaleString() }}
              </template>
            </el-table-column>
          </el-table>
          <el-pagination
            v-model:current-page="query.page"
            :page-size="query.limit"
            :total="snapshotTotal"
            layout="total, prev, pager, next"
            @current-change="fetchSnapshots"
          />
        </el-tab-pane>

        <el-tab-pane label="维度权重" name="weights">
          <el-table v-loading="loading" :data="weightData" stripe>
            <el-table-column prop="id" label="ID" width="80" />
            <el-table-column prop="job_category" label="岗位类别" />
            <el-table-column prop="top_dimension" label="维度" />
            <el-table-column label="权重" width="150">
              <template #default="{ row }">
                <el-progress :percentage="Math.round(row.weight * 100)" />
              </template>
            </el-table-column>
          </el-table>
          <el-pagination
            v-model:current-page="query.page"
            :page-size="query.limit"
            :total="weightTotal"
            layout="total, prev, pager, next"
            @current-change="fetchWeights"
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

.toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}
</style>
