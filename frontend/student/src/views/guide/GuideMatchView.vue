<script setup lang="ts">
/**
 * 引导第 3 步：人岗匹配选岗
 * 1) 取画像快照 ID（journey.snapshotId，缺失时 fetchStatus 兜底）
 * 2) POST /matching/run { profile_snapshot_id, top_k: 10 }（results 恰 3 项，match_score 为 0~1 比例）
 * 3) 逐个拉取岗位详情（单项失败仅该项降级，不影响其余卡片）
 * 4) 确认 → localStorage('guide.matching_results') 恰 3 项 + 'guide.selected_job' 种子 → setGuideStep('career')
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh, Search, WarningFilled } from '@element-plus/icons-vue'
import { matchingApi, type MatchRunResponse } from '@/api/matching'
import { jobsApi, type JobProfileResponse } from '@/api/jobs'
import { useJourneyStore } from '@/stores/journey'
import SectionCard from '@/components/SectionCard.vue'
import ScoreBadge from '@/components/ScoreBadge.vue'
import DimensionBar from '@/components/DimensionBar.vue'
import EmptyState from '@/components/EmptyState.vue'

/* 第 4 步 GuideCareerView 复用本类型（保持与匹配契约同构） */
export type MatchedItem = MatchRunResponse['results'][number]

const MATCHING_RESULTS_KEY = 'guide.matching_results'
const SELECTED_JOB_KEY = 'guide.selected_job'

/** 模块级标记：HMR 重挂载时同模块状态会保留，避免自动重复发起匹配 */
let autoRunDone = false

const router = useRouter()
const journey = useJourneyStore()

const loading = ref(false)
const confirming = ref(false)
const matches = ref<MatchedItem[]>([])
const jobDetails = ref<Record<number, JobProfileResponse | null>>({})
const error = ref('')
const snapshotMissing = ref(false)

/** 匹配失败只置 error（axios 拦截器已对非 401 弹一次提示，此处不再重复 toast） */
function handleMatchError(err: unknown): void {
  const detail = (err as { response?: { data?: { detail?: unknown } } } | null)?.response?.data?.detail
  error.value = typeof detail === 'string' && detail.trim() ? detail : '匹配失败，请重试'
}

/** 快照 ID：优先 store，其次 fetchStatus 后重读（401 时 fetchStatus 会抛，单独兜底） */
async function resolveSnapshotId(): Promise<number | null> {
  if (journey.snapshotId != null) return journey.snapshotId
  try {
    await journey.fetchStatus()
  } catch {
    /* 离线 / 401 等：重读 store，仍为空则走缺失分支 */
  }
  return journey.snapshotId ?? null
}

async function loadJobDetails(items: MatchedItem[]): Promise<void> {
  const entries = await Promise.all(
    items.map(async (item): Promise<[number, JobProfileResponse | null]> => {
      try {
        return [item.job_profile_id, await jobsApi.getDetail(item.job_profile_id)]
      } catch {
        return [item.job_profile_id, null]   // 单个岗位详情失败仅降级该卡片
      }
    }),
  )
  jobDetails.value = Object.fromEntries(entries)
}

/** 重新匹配：清空结果 → 解析快照 → 拉详情（单项失败不阻断） */
async function runMatch(): Promise<void> {
  if (loading.value) return
  loading.value = true
  error.value = ''
  snapshotMissing.value = false
  matches.value = []
  jobDetails.value = {}
  try {
    const snapshotId = await resolveSnapshotId()
    if (snapshotId == null) {
      snapshotMissing.value = true
      return
    }
    const res = await matchingApi.runMatch(snapshotId, 10)
    const items = Array.isArray(res?.results) ? res.results : []   // results 可能为 []（岗位向量库为空）
    matches.value = items
    if (items.length > 0) await loadJobDetails(items)
  } catch (err) {
    handleMatchError(err)
  } finally {
    loading.value = false
  }
}

/** 首次进入自动匹配一次（HMR 重挂载不重复发起） */
async function bootstrap(): Promise<void> {
  if (autoRunDone) return
  autoRunDone = true
  await runMatch()
}

onMounted(() => { void bootstrap() })

function formatPercent(value: number | null | undefined): string {
  return `${Math.round((value ?? 0) * 100)}%`
}

function formatSummary(summary: string | null, max = 84): string {
  const text = (summary ?? '').trim()
  return text.length > max ? `${text.slice(0, max)}…` : text
}

function detailOf(id: number): JobProfileResponse | null {
  return jobDetails.value[id] ?? null
}

/** 逐维度渲染行：value 用 user_score，进度条满量程取双方较大值 */
function dimensionRows(item: MatchedItem) {
  return Object.entries(item.analysis?.dimension_matches ?? {}).map(([key, detail]) => ({
    key,
    detail,
    max: Math.max(detail.job_score, detail.user_score, 0.01),
  }))
}

const hasMatches = computed(() => matches.value.length > 0)

function confirmSelection(): void {
  if (!hasMatches.value || confirming.value) return
  const top = matches.value[0]
  confirming.value = true
  try {
    localStorage.setItem(
      MATCHING_RESULTS_KEY,
      JSON.stringify(matches.value.map(m => ({
        job_profile_id: m.job_profile_id,
        match_score: m.match_score,
      }))),
    )
    localStorage.setItem(
      SELECTED_JOB_KEY,
      JSON.stringify({
        job_profile_id: top.job_profile_id,
        title: detailOf(top.job_profile_id)?.title ?? '',
      }),
    )
  } catch (e) {
    console.warn('[guide-match] 选岗结果缓存失败，流程继续', e)
    ElMessage.warning('选岗结果本地缓存失败，后续步骤可能需要重新匹配')
  }
  journey.setGuideStep('career')
  router.push('/guide/career')
}
</script>

<template>
  <div class="guide-page">
    <header class="page-head">
      <h2 class="guide-title">选择岗位</h2>
      <p class="guide-desc">
        已按你的画像快照匹配出最契合的岗位。确认后进入匹配策略，挑选 1 个主攻岗。
      </p>
    </header>

    <!-- 加载中 -->
    <div v-if="loading" class="state-box">
      <el-icon class="is-loading" :size="24"><Refresh /></el-icon>
      <p class="state-text">正在执行人岗匹配…</p>
    </div>

    <!-- 缺少画像快照 -->
    <EmptyState
      v-else-if="snapshotMissing"
      :icon="WarningFilled"
      title="尚未生成画像快照"
      description="需要先完成画像解析并生成快照，才能执行人岗匹配。"
      show-action
      action-text="回到画像解析"
      @action="router.push('/guide/parse')"
    />

    <!-- 匹配失败 -->
    <EmptyState
      v-else-if="error"
      :icon="WarningFilled"
      title="匹配失败"
      :description="error"
      show-action
      action-text="重试匹配"
      @action="runMatch"
    />

    <!-- 无匹配结果（岗位向量库为空是合法状态） -->
    <EmptyState
      v-else-if="!hasMatches"
      :icon="Search"
      title="暂无匹配岗位"
      description="岗位库还没有可用的岗位向量，或本次匹配没有返回结果。可稍后重新匹配，或先请管理员补充岗位库。"
      show-action
      action-text="重新匹配"
      @action="runMatch"
    />

    <!-- 匹配结果卡片 -->
    <template v-else>
      <SectionCard
        v-for="(item, index) in matches"
        :key="item.job_profile_id"
        :title="detailOf(item.job_profile_id)?.title || `岗位 #${item.job_profile_id}`"
        :subtitle="`第 ${index + 1} 名推荐`"
        class="job-card hover-lift"
      >
        <template #header>
          <ScoreBadge :score="Math.round(item.match_score * 100)" size="large" show-label />
        </template>

        <template v-if="detailOf(item.job_profile_id)">
          <div class="meta-tags">
            <span v-if="detailOf(item.job_profile_id)?.industry" class="tag">
              {{ detailOf(item.job_profile_id)?.industry }}
            </span>
            <span v-if="detailOf(item.job_profile_id)?.level" class="tag">
              {{ detailOf(item.job_profile_id)?.level }}
            </span>
            <span v-if="detailOf(item.job_profile_id)?.salary_range" class="tag tag-brand">
              {{ detailOf(item.job_profile_id)?.salary_range }}
            </span>
          </div>
          <p
            v-if="detailOf(item.job_profile_id)?.education_requirement || detailOf(item.job_profile_id)?.experience_requirement"
            class="requirement"
          >
            <span v-if="detailOf(item.job_profile_id)?.education_requirement">
              学历：{{ detailOf(item.job_profile_id)?.education_requirement }}
            </span>
            <span v-if="detailOf(item.job_profile_id)?.experience_requirement">
              经验：{{ detailOf(item.job_profile_id)?.experience_requirement }}
            </span>
          </p>
          <p v-if="formatSummary(detailOf(item.job_profile_id)?.summary ?? null)" class="summary">
            {{ formatSummary(detailOf(item.job_profile_id)?.summary ?? null) }}
          </p>
        </template>
        <p v-else class="detail-fallback">岗位详情暂时获取失败，仅展示匹配分数。</p>

        <div class="analysis">
          <div class="analysis-head">
            <span class="analysis-title">六维契合度</span>
            <span class="analysis-meta">
              向量相似 {{ formatPercent(item.analysis?.vector_similarity) }} ·
              维度得分 {{ formatPercent(item.analysis?.dimension_score) }}
            </span>
          </div>
          <ul v-if="dimensionRows(item).length" class="dim-list">
            <li v-for="row in dimensionRows(item)" :key="row.key" class="dim-row">
              <DimensionBar
                :label="row.key"
                :value="row.detail.user_score"
                :max="row.max"
                :show-value="false"
              />
              <span class="dim-ratio">{{ formatPercent(row.detail.match_ratio) }}</span>
            </li>
          </ul>
          <p v-else class="dim-empty">本次匹配未返回维度明细。</p>
        </div>
      </SectionCard>
    </template>

    <div class="confirm-bar">
      <el-button
        type="primary"
        class="confirm-btn hover-lift press-effect"
        :loading="confirming"
        :disabled="!hasMatches"
        @click="confirmSelection"
      >
        确认选这些岗位
      </el-button>
    </div>
  </div>
</template>

<style scoped>
.guide-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}
.page-head {
  text-align: center;
}
.guide-title {
  font-family: var(--font-display);
  font-size: 28px;
  font-weight: 600;
  color: var(--c-text-1);
  margin: 0 0 var(--space-3);
}
.guide-desc {
  font-size: 15px;
  color: var(--c-text-2);
  margin: 0;
  line-height: 1.6;
}

/* 状态区 */
.state-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  min-height: 200px;
  background: var(--c-surface);
  border: 1px solid var(--c-bg-mute);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-xs);
  color: var(--c-text-3);
}
.state-text {
  font-size: var(--text-sm);
  margin: 0;
}

/* 岗位卡片 */
.job-card {
  transition: box-shadow 0.2s ease;
}
.meta-tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
.tag {
  font-size: var(--text-xs);
  color: var(--c-text-2);
  background: var(--c-bg-soft);
  border-radius: var(--radius-full);
  padding: var(--space-1) var(--space-3);
}
.tag-brand {
  color: var(--c-brand);
  background: var(--c-brand-lighter);
}
.requirement {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2) var(--space-4);
  margin: var(--space-3) 0 0;
  font-size: var(--text-xs);
  color: var(--c-text-3);
}
.summary {
  margin: var(--space-3) 0 0;
  font-size: var(--text-sm);
  color: var(--c-text-2);
  line-height: 1.6;
}
.detail-fallback {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--c-text-3);
}

/* 六维对比 */
.analysis {
  margin-top: var(--space-4);
  padding-top: var(--space-4);
  border-top: 1px solid var(--c-bg-mute);
}
.analysis-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}
.analysis-title {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--c-text-1);
}
.analysis-meta {
  font-size: var(--text-xs);
  color: var(--c-text-3);
}
.dim-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
}
.dim-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.dim-ratio {
  flex-shrink: 0;
  width: 44px;
  text-align: right;
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--c-text-2);
}
.dim-empty {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--c-text-3);
}

/* 确认区 */
.confirm-bar {
  display: flex;
  justify-content: center;
  padding: var(--space-2) 0 var(--space-4);
}
.confirm-btn {
  min-width: 220px;
  border-radius: var(--radius-full);
  font-weight: 600;
}

@media (max-width: 768px) {
  .guide-title {
    font-size: 22px;
  }
  .analysis-head {
    flex-direction: column;
  }
}
</style>
