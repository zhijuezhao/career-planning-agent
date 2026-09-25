<script setup lang="ts">
/**
 * 匹配管理（B2-3 起含「匹配明细」）
 *
 * 三个页签：
 * - 画像快照：谁生成了快照、匹配状态（matched_at）、六维分数；行内「明细」跳转到本快照的匹配明细
 * - **匹配明细**：`job_match_records` 逐条结果（排名/得分/距离/状态/耗时 + analysis 详情）
 * - 维度权重：人岗匹配用的维度权重表
 *
 * 明细语义（后端 `match_record_service`）：**同一快照重复匹配 = 覆盖**，
 * 所以这里看到的永远是该快照最近一次运行的结果；`status=failed` 表示该岗位单条打分失败。
 */
import { onMounted, reactive, ref } from 'vue'
import { get } from '@/api/request'
import { DetailDialog } from '@/components'
import type { DetailTag } from '@/components'
import { formatDateTime } from '@/utils/preview'

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

interface MatchRecord {
  id: number
  profile_snapshot_id: number
  snapshot_serial_no: string | null
  user_id: number | null
  username: string | null
  job_profile_id: number
  job_title: string | null
  rank: number
  score: number | null
  distance: number | null
  status: string
  duration_ms: number | null
  matched_at: string
}

interface MatchRecordDetail extends MatchRecord {
  analysis: Record<string, unknown> | null
  job_industry: string | null
}

interface MatchRecordStats {
  total: number
  success: number
  failed: number
  snapshots: number
  avg_score: number | null
  avg_duration_ms: number | null
}

const loading = ref(false)
const snapshotData = ref<Snapshot[]>([])
const weightData = ref<Weight[]>([])
const recordData = ref<MatchRecord[]>([])
const snapshotTotal = ref(0)
const weightTotal = ref(0)
const recordTotal = ref(0)
const activeTab = ref('snapshots')

const recordStats = ref<MatchRecordStats | null>(null)

const query = reactive({
  page: 1,
  limit: 20,
  user_id: undefined as number | undefined,
  matched: '' as '' | 'true' | 'false',
  // 明细筛选
  snapshot_id: undefined as number | undefined,
  job_profile_id: undefined as number | undefined,
  status: '' as '' | 'success' | 'failed',
})

/** 六维分数摘要（形如：技能 4.2 · 实践 3.8 ...） */
const dimSummary = (scores: Record<string, number>) =>
  Object.entries(scores || {})
    .map(([k, v]) => `${k} ${Number(v).toFixed(1)}`)
    .join(' · ')

const fetchSnapshots = async () => {
  loading.value = true
  try {
    const params: Record<string, unknown> = {
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

const fetchRecords = async () => {
  loading.value = true
  try {
    const params: Record<string, unknown> = {
      skip: (query.page - 1) * query.limit,
      limit: query.limit,
    }
    if (query.snapshot_id) params.snapshot_id = query.snapshot_id
    if (query.user_id) params.user_id = query.user_id
    if (query.job_profile_id) params.job_profile_id = query.job_profile_id
    if (query.status !== '') params.status = query.status
    const res = await get<{ items: MatchRecord[]; total: number }>('/v1/admin/matching/records', {
      params,
    })
    recordData.value = res.items
    recordTotal.value = res.total
  } catch {
    // error handled by interceptor
  } finally {
    loading.value = false
  }
}

const fetchRecordStats = async () => {
  try {
    recordStats.value = await get<MatchRecordStats>('/v1/admin/matching/records/stats')
  } catch {
    // error handled by interceptor
  }
}

const handleSearch = () => {
  query.page = 1
  if (activeTab.value === 'records') fetchRecords()
  else fetchSnapshots()
}

const handleTabChange = (tab: string) => {
  query.page = 1
  if (tab === 'snapshots') fetchSnapshots()
  else if (tab === 'weights') fetchWeights()
  else if (tab === 'records') {
    fetchRecords()
    fetchRecordStats()
  }
}

/** 从快照行跳到「匹配明细」并按该快照过滤 */
const openSnapshotRecords = (row: Snapshot) => {
  query.snapshot_id = row.id
  query.status = ''
  query.page = 1
  activeTab.value = 'records'
  fetchRecords()
  fetchRecordStats()
}

const resetRecordFilters = () => {
  query.snapshot_id = undefined
  query.job_profile_id = undefined
  query.status = ''
  query.page = 1
  fetchRecords()
}

onMounted(fetchSnapshots)

// ── 明细详情（analysis） ─────────────────────────────────────────────────────

const detailVisible = ref(false)
const detailTitle = ref('')
const detailSubtitle = ref('')
const detailTags = ref<DetailTag[]>([])
const detailMarkdown = ref('')
const detailJson = ref<unknown>(undefined)

const openRecordDetail = async (row: MatchRecord) => {
  try {
    const detail = await get<MatchRecordDetail>(`/v1/admin/matching/records/${row.id}`)
    detailTitle.value = `匹配明细 #${detail.id}`
    detailSubtitle.value = `快照 ${detail.profile_snapshot_id} · 岗位 #${detail.job_profile_id}`
    const tags: DetailTag[] = [
      { text: detail.status === 'success' ? '成功' : '失败', type: detail.status === 'success' ? 'success' : 'danger' },
      { text: `第 ${detail.rank} 名`, type: 'primary' },
    ]
    if (detail.score !== null) tags.push({ text: `得分 ${detail.score}`, type: 'warning' })
    if (detail.duration_ms !== null) tags.push({ text: `耗时 ${detail.duration_ms} ms`, type: 'info' })
    detailTags.value = tags

    const analysis = (detail.analysis || {}) as Record<string, any>
    const lines = [
      `**岗位**：${detail.job_title ?? '-'}（#${detail.job_profile_id}）`,
      `**快照**：${detail.profile_snapshot_id}${detail.snapshot_serial_no ? ` · ${detail.snapshot_serial_no}` : ''}`,
      `**用户**：${detail.username ?? detail.user_id ?? '-'}`,
      `**状态**：${detail.status}`,
      `**排名**：${detail.rank}`,
      `**综合得分**：${detail.score ?? '-'}`,
      `**向量距离**：${detail.distance ?? '-'}`,
      `**耗时**：${detail.duration_ms ?? '-'} ms`,
    ]
    if (analysis.error) lines.push('', `**失败原因**：${analysis.error}`)
    if (analysis.vector_similarity !== undefined) {
      lines.push(
        '',
        '### 打分构成',
        `- 向量相似度：${analysis.vector_similarity}`,
        `- 维度匹配分：${analysis.dimension_score}`,
      )
    }
    const matches = (analysis.dimension_matches || {}) as Record<string, any>
    const dimRows = Object.entries(matches)
    if (dimRows.length) {
      lines.push('', '### 六维对比', '| 维度 | 用户 | 岗位 | 权重 | 匹配度 |', '|---|---|---|---|---|')
      for (const [dim, m] of dimRows) {
        lines.push(`| ${dim} | ${m.user_score} | ${m.job_score} | ${m.weight} | ${m.match_ratio} |`)
      }
    }
    detailMarkdown.value = lines.join('\n')
    detailJson.value = detail.analysis
    detailVisible.value = true
  } catch {
    // error handled by interceptor
  }
}
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
            <el-table-column label="六维分数" min-width="280" show-overflow-tooltip>
              <template #default="{ row }">{{ dimSummary(row.six_dim_scores) || '-' }}</template>
            </el-table-column>
            <el-table-column prop="description" label="描述" width="120" />
            <el-table-column label="创建时间" width="180">
              <template #default="{ row }">
                {{ formatDateTime(row.created_at) }}
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100" fixed="right">
              <template #default="{ row }">
                <el-button type="primary" size="small" link @click="openSnapshotRecords(row)">
                  明细
                </el-button>
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

        <el-tab-pane label="匹配明细" name="records">
          <el-alert
            type="info"
            :closable="false"
            show-icon
            title="同一快照重复匹配会覆盖上一轮明细"
            description="这里展示的是每个快照最近一次运行的逐条结果（排名按得分倒序）；状态「失败」表示该岗位单条打分失败，不影响其他岗位。"
            class="hint"
          />

          <div v-if="recordStats" class="stats-row">
            <el-tag type="info">明细 {{ recordStats.total }}</el-tag>
            <el-tag type="success">成功 {{ recordStats.success }}</el-tag>
            <el-tag type="danger">失败 {{ recordStats.failed }}</el-tag>
            <el-tag type="warning">涉及快照 {{ recordStats.snapshots }}</el-tag>
            <el-tag v-if="recordStats.avg_score !== null" type="primary">
              平均分 {{ recordStats.avg_score }}
            </el-tag>
            <el-tag v-if="recordStats.avg_duration_ms !== null">
              平均耗时 {{ recordStats.avg_duration_ms }} ms
            </el-tag>
          </div>

          <div class="toolbar">
            <el-input
              v-model.number="query.snapshot_id"
              placeholder="快照ID"
              style="width: 130px"
              clearable
            />
            <el-input
              v-model.number="query.user_id"
              placeholder="用户ID"
              style="width: 130px"
              clearable
            />
            <el-input
              v-model.number="query.job_profile_id"
              placeholder="岗位ID"
              style="width: 130px"
              clearable
            />
            <el-select v-model="query.status" placeholder="状态" style="width: 130px">
              <el-option label="全部" value="" />
              <el-option label="成功" value="success" />
              <el-option label="失败" value="failed" />
            </el-select>
            <el-button type="primary" @click="handleSearch">搜索</el-button>
            <el-button @click="resetRecordFilters">重置</el-button>
            <el-button @click="fetchRecords">刷新</el-button>
          </div>

          <el-table v-loading="loading" :data="recordData" stripe>
            <el-table-column label="匹配时间" width="170">
              <template #default="{ row }">{{ formatDateTime(row.matched_at) }}</template>
            </el-table-column>
            <el-table-column prop="rank" label="排名" width="70" />
            <el-table-column label="用户" width="140" show-overflow-tooltip>
              <template #default="{ row }">{{ row.username ?? row.user_id ?? '-' }}</template>
            </el-table-column>
            <el-table-column prop="profile_snapshot_id" label="快照ID" width="90" />
            <el-table-column label="岗位" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.job_title ?? '（岗位已删除）' }} #{{ row.job_profile_id }}
              </template>
            </el-table-column>
            <el-table-column label="得分" width="100">
              <template #default="{ row }">{{ row.score ?? '-' }}</template>
            </el-table-column>
            <el-table-column label="距离" width="100">
              <template #default="{ row }">{{ row.distance ?? '-' }}</template>
            </el-table-column>
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="row.status === 'success' ? 'success' : 'danger'" size="small">
                  {{ row.status === 'success' ? '成功' : '失败' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="耗时" width="100">
              <template #default="{ row }">{{ row.duration_ms ?? '-' }} ms</template>
            </el-table-column>
            <el-table-column label="操作" width="90" fixed="right">
              <template #default="{ row }">
                <el-button type="primary" size="small" link @click="openRecordDetail(row)">
                  详情
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-pagination
            v-model:current-page="query.page"
            :page-size="query.limit"
            :total="recordTotal"
            layout="total, prev, pager, next"
            @current-change="fetchRecords"
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

    <DetailDialog
      v-model="detailVisible"
      :title="detailTitle"
      :subtitle="detailSubtitle"
      :tags="detailTags"
      :markdown="detailMarkdown"
      :json="detailJson"
      width="820px"
      empty-text="（该明细没有打分分析数据）"
    />
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
  flex-wrap: wrap;
}

.hint {
  margin-bottom: 12px;
}

.stats-row {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
</style>
