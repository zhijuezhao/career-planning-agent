<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { get, post, put, remove } from '@/api/request'

interface MatchResult {
  id: number
  user_id: number
  profile_id: number
  job_profile_id: number
  match_score: number | null
  created_at: string
}

interface Feedback {
  id: number
  user_id: number
  match_id: number
  feedback_type: string | null
  comment: string | null
  created_at: string
}

interface Weight {
  id: number
  job_category: string
  top_dimension: string
  weight: number
}

const loading = ref(false)
const matchData = ref<MatchResult[]>([])
const feedbackData = ref<Feedback[]>([])
const weightData = ref<Weight[]>([])
const matchTotal = ref(0)
const feedbackTotal = ref(0)
const weightTotal = ref(0)
const activeTab = ref('results')

const query = reactive({
  page: 1,
  limit: 20,
  min_score: undefined as number | undefined,
})

const fetchResults = async () => {
  loading.value = true
  try {
    const params: Record<string, any> = {
      skip: (query.page - 1) * query.limit,
      limit: query.limit,
    }
    if (query.min_score) params.min_score = query.min_score
    const res = await get<{ items: MatchResult[]; total: number }>('/v1/admin/matching/results', { params })
    matchData.value = res.items
    matchTotal.value = res.total
  } catch {
    // error handled by interceptor
  } finally {
    loading.value = false
  }
}

const fetchFeedbacks = async () => {
  loading.value = true
  try {
    const res = await get<{ items: Feedback[]; total: number }>('/v1/admin/matching/feedbacks', {
      params: { skip: (query.page - 1) * query.limit, limit: query.limit },
    })
    feedbackData.value = res.items
    feedbackTotal.value = res.total
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

const handleTabChange = (tab: string) => {
  query.page = 1
  if (tab === 'results') fetchResults()
  else if (tab === 'feedbacks') fetchFeedbacks()
  else if (tab === 'weights') fetchWeights()
}

onMounted(fetchResults)
</script>

<template>
  <div>
    <el-card class="data-card">
      <el-tabs v-model="activeTab" @tab-change="handleTabChange">
        <el-tab-pane label="匹配结果" name="results">
          <el-table v-loading="loading" :data="matchData" stripe>
            <el-table-column prop="id" label="ID" width="80" />
            <el-table-column prop="user_id" label="用户ID" width="100" />
            <el-table-column prop="job_profile_id" label="岗位ID" width="100" />
            <el-table-column label="匹配度" width="150">
              <template #default="{ row }">
                <el-progress
                  :percentage="row.match_score ? Math.round(row.match_score * 100) : 0"
                  :color="row.match_score && row.match_score > 0.7 ? '#67c23a' : '#e6a23c'"
                />
              </template>
            </el-table-column>
            <el-table-column label="创建时间">
              <template #default="{ row }">
                {{ new Date(row.created_at).toLocaleString() }}
              </template>
            </el-table-column>
          </el-table>
          <el-pagination
            v-model:current-page="query.page"
            :page-size="query.limit"
            :total="matchTotal"
            layout="total, prev, pager, next"
            @current-change="fetchResults"
          />
        </el-tab-pane>

        <el-tab-pane label="用户反馈" name="feedbacks">
          <el-table v-loading="loading" :data="feedbackData" stripe>
            <el-table-column prop="id" label="ID" width="80" />
            <el-table-column prop="user_id" label="用户ID" width="100" />
            <el-table-column prop="match_id" label="匹配ID" width="100" />
            <el-table-column label="反馈类型" width="120">
              <template #default="{ row }">
                <el-tag :type="row.feedback_type === 'like' ? 'success' : 'info'" size="small">
                  {{ row.feedback_type || '-' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="comment" label="备注" />
          </el-table>
          <el-pagination
            v-model:current-page="query.page"
            :page-size="query.limit"
            :total="feedbackTotal"
            layout="total, prev, pager, next"
            @current-change="fetchFeedbacks"
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
</style>
