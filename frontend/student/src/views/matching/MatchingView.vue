<script setup lang="ts">
/**
 * 岗位匹配页面（Task 16 迁移：旧契约 → matchSnapshot 契约）
 * 调用的后端API：
 *   - GET  /api/v1/journey/status             取最新画像快照 id
 *   - POST /api/v1/matching/run               执行人岗匹配（入参 profile_snapshot_id + top_k + max_distance）
 *   - GET  /api/v1/jobs/{job_id}              岗位详情（用于卡片展示）
 * 迁移说明：
 *   - 旧 `/matching/results`（匹配历史）与 `/matching/feedback`（反馈）端点已随旧表删除，
 *     故「历史列表」区块不再加载（无端点），「反馈」改为**本地收藏**（localStorage，不落库）。
 *   - 匹配入参由 profile_id 改为 profile_snapshot_id（后端 Task 5 契约）。
 */
import { ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Opportunity,
  Loading,
  Warning,
  Star,
  StarFilled,
  Promotion,
  DataAnalysis,
} from '@element-plus/icons-vue'
import { matchingApi, type MatchResultItem, type MatchRunResponse } from '../../api/matching'
import { jobsApi, type JobProfileResponse } from '../../api/jobs'
import { useJourneyStore } from '../../stores/journey'

/** 本地收藏键（后端反馈端点已删除，收藏仅存本地） */
const FAVORITES_KEY = 'matching.favorites.v1'

// ==================== 状态 ====================

const journey = useJourneyStore()
const loading = ref(false)
const matching = ref(false)
const matchResult = ref<MatchRunResponse | null>(null)
const jobDetailsMap = ref<Record<number, JobProfileResponse>>({})
/** 本地收藏的岗位 id → 标记值（沿用原 feedbackGiven 的展示语义） */
const favorites = ref<Record<number, string>>({})

// 匹配参数（阈值默认与后端一致：0.65，见 R-11.6）
const topK = ref(10)
const maxDistance = ref(0.65)

// ==================== 计算属性 ====================

const hasProfile = computed(() => journey.snapshotId != null)
const profileId = computed(() => journey.snapshotId)

const matchResults = computed(() => matchResult.value?.results || [])

// ==================== 方法 ====================

function loadFavorites() {
  try {
    const raw = localStorage.getItem(FAVORITES_KEY)
    if (!raw) return
    const parsed: unknown = JSON.parse(raw)
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      favorites.value = parsed as Record<number, string>
    }
  } catch {
    /* 解析失败忽略 */
  }
}

function persistFavorites() {
  try {
    localStorage.setItem(FAVORITES_KEY, JSON.stringify(favorites.value))
  } catch {
    /* localStorage 不可用时忽略 */
  }
}

async function loadJobDetail(jobProfileId: number) {
  if (jobDetailsMap.value[jobProfileId]) return
  try {
    const detail = await jobsApi.getDetail(jobProfileId)
    jobDetailsMap.value[jobProfileId] = detail
  } catch {
    // 岗位详情加载失败不影响主流程
  }
}

async function runMatching() {
  if (profileId.value == null) {
    ElMessage.warning('请先上传简历并完成解析，生成画像快照')
    return
  }

  matching.value = true
  try {
    const result = await matchingApi.runMatch(profileId.value, topK.value)
    matchResult.value = result

    // 预加载所有岗位详情
    for (const item of result.results) {
      void loadJobDetail(item.job_profile_id)
    }

    if ((result.total ?? 0) === 0) {
      ElMessage.info('暂无匹配的岗位，可放宽距离阈值后重试')
    } else {
      ElMessage.success(`匹配完成，共 ${result.total} 个岗位`)
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '匹配执行失败')
  } finally {
    matching.value = false
  }
}

/** 本地收藏（原「反馈」端已删除；此操作不请求后端） */
function toggleFavorite(item: MatchResultItem) {
  const id = item.job_profile_id
  if (favorites.value[id]) {
    delete favorites.value[id]
    ElMessage.info('已取消收藏')
  } else {
    favorites.value[id] = 'saved'
    ElMessage.success('已收藏（仅本地记录）')
  }
  persistFavorites()
}

/** 供模板复用：该岗位是否已收藏 */
function isFavorite(item: MatchResultItem): boolean {
  return !!favorites.value[item.job_profile_id]
}

function getScoreColor(score: number): string {
  if (score >= 0.8) return '#22c55e'
  if (score >= 0.6) return '#6366f1'
  if (score >= 0.4) return '#f59e0b'
  return '#ef4444'
}

function getScoreLabel(score: number): string {
  if (score >= 0.8) return '高度匹配'
  if (score >= 0.6) return '较为匹配'
  if (score >= 0.4) return '一般匹配'
  return '匹配度低'
}

function getMatchRatioColor(ratio: number): string {
  if (ratio >= 0.8) return '#22c55e'
  if (ratio >= 0.6) return '#6366f1'
  if (ratio >= 0.4) return '#f59e0b'
  return '#ef4444'
}

function formatPercent(value: number): string {
  return (value * 100).toFixed(1) + '%'
}

// ==================== 生命周期 ====================

onMounted(async () => {
  loading.value = true
  loadFavorites()
  try {
    await journey.fetchStatus()
  } catch {
    /* 离线等场景忽略：hasProfile 回落 false */
  }
  // 有快照则自动跑一次匹配（沿用原「进入即加载历史」的体验）
  if (journey.snapshotId != null) {
    await runMatching()
  }
  loading.value = false
})
</script>

<template>
  <div class="matching-page">
    <!-- 加载状态 -->
    <div v-if="loading" class="loading-container">
      <el-icon :size="32" class="is-loading" color="var(--c-brand)"><Loading /></el-icon>
      <p>正在加载匹配数据...</p>
    </div>

    <!-- 空状态：无画像 -->
    <div v-else-if="!hasProfile" class="empty-state">
      <el-icon :size="48" color="var(--c-text-3)"><Warning /></el-icon>
      <h3>暂无能力画像</h3>
      <p>请先上传简历并完成解析，才能进行岗位匹配</p>
      <el-button type="primary" @click="$router.push('/resume')">前往上传简历</el-button>
    </div>

    <!-- 匹配内容 -->
    <div v-else class="matching-content">
      <!-- 匹配控制面板 -->
      <div class="widget control-panel">
        <div class="widget-header">
          <div class="header-left">
            <el-icon :size="18" color="var(--c-brand)"><Opportunity /></el-icon>
            <span class="widget-title">智能岗位匹配</span>
          </div>
          <span class="profile-badge">画像 #{{ profileId }}</span>
        </div>
        <div class="control-body">
          <div class="control-row">
            <div class="control-item">
              <label class="control-label">返回数量</label>
              <el-slider
                v-model="topK"
                :min="1"
                :max="30"
                :step="1"
                show-input
                :show-input-controls="false"
                input-size="small"
              />
              <span class="control-value">{{ topK }} 个</span>
            </div>
            <div class="control-item">
              <label class="control-label">距离阈值</label>
              <el-slider
                v-model="maxDistance"
                :min="0.1"
                :max="1.0"
                :step="0.05"
                show-input
                :show-input-controls="false"
                input-size="small"
              />
              <span class="control-value">{{ maxDistance.toFixed(2) }}</span>
            </div>
          </div>
          <div class="control-actions">
            <el-button
              type="primary"
              :loading="matching"
              :icon="Promotion"
              @click="runMatching"
            >
              {{ matching ? '匹配中...' : '开始匹配' }}
            </el-button>
            <span class="control-hint">
              基于向量相似度(40%) + 维度加权评分(60%) 综合匹配
            </span>
          </div>
        </div>
      </div>

      <!-- 匹配结果 -->
      <div v-if="matchResults.length > 0" class="results-section">
        <div class="section-header">
          <el-icon :size="16" color="var(--c-brand)"><DataAnalysis /></el-icon>
          <span class="section-title">匹配结果</span>
          <span class="section-count">共 {{ matchResult?.total || 0 }} 个岗位</span>
        </div>

        <div class="results-grid">
          <div
            v-for="(item, idx) in matchResults"
            :key="item.job_profile_id"
            class="result-card"
            :class="{ top: idx < 3 }"
          >
            <!-- 排名标识 -->
            <div class="rank-badge" :class="`rank-${idx + 1}`">
              {{ idx + 1 }}
            </div>

            <!-- 卡片头部 -->
            <div class="card-header">
              <div class="job-title-row">
                <h3 class="job-title">
                  {{ jobDetailsMap[item.job_profile_id]?.title || `岗位 #${item.job_profile_id}` }}
                </h3>
                <div class="job-meta">
                  <el-tag v-if="jobDetailsMap[item.job_profile_id]?.industry" size="small" effect="plain">
                    {{ jobDetailsMap[item.job_profile_id].industry }}
                  </el-tag>
                  <el-tag v-if="jobDetailsMap[item.job_profile_id]?.level" size="small" type="success" effect="plain">
                    {{ jobDetailsMap[item.job_profile_id].level }}
                  </el-tag>
                </div>
              </div>
              <div class="match-score-badge" :style="{ backgroundColor: getScoreColor(item.match_score) }">
                <span class="score-value">{{ formatPercent(item.match_score) }}</span>
                <span class="score-label">{{ getScoreLabel(item.match_score) }}</span>
              </div>
            </div>

            <!-- 岗位信息 -->
            <div class="job-info">
              <div v-if="jobDetailsMap[item.job_profile_id]?.salary_range" class="info-item">
                <span class="info-label">薪资</span>
                <span class="info-value">{{ jobDetailsMap[item.job_profile_id].salary_range }}</span>
              </div>
              <div v-if="jobDetailsMap[item.job_profile_id]?.education_requirement" class="info-item">
                <span class="info-label">学历</span>
                <span class="info-value">{{ jobDetailsMap[item.job_profile_id].education_requirement }}</span>
              </div>
              <div v-if="jobDetailsMap[item.job_profile_id]?.experience_requirement" class="info-item">
                <span class="info-label">经验</span>
                <span class="info-value">{{ jobDetailsMap[item.job_profile_id].experience_requirement }}</span>
              </div>
            </div>

            <!-- 维度分析 -->
            <div class="analysis-section">
              <div class="analysis-header">
                <span class="analysis-title">匹配分析</span>
                <div class="analysis-scores">
                  <span class="analysis-tag vector">
                    向量 {{ formatPercent(item.analysis.vector_similarity) }}
                  </span>
                  <span class="analysis-tag dimension">
                    维度 {{ formatPercent(item.analysis.dimension_score) }}
                  </span>
                </div>
              </div>

              <!-- 维度匹配条 -->
              <div v-if="item.analysis.dimension_matches" class="dimension-bars">
                <div
                  v-for="(detail, dim) in item.analysis.dimension_matches"
                  :key="dim"
                  class="dim-bar-item"
                >
                  <span class="dim-name">{{ dim }}</span>
                  <div class="dim-bar-bg">
                    <div
                      class="dim-bar-fill"
                      :style="{
                        width: `${(detail.match_ratio || 0) * 100}%`,
                        backgroundColor: getMatchRatioColor(detail.match_ratio || 0),
                      }"
                    ></div>
                  </div>
                  <span class="dim-value" :style="{ color: getMatchRatioColor(detail.match_ratio || 0) }">
                    {{ formatPercent(detail.match_ratio || 0) }}
                  </span>
                </div>
              </div>
            </div>

            <!-- 岗位描述摘要 -->
            <div v-if="jobDetailsMap[item.job_profile_id]?.summary" class="job-summary">
              {{ jobDetailsMap[item.job_profile_id].summary }}
            </div>

            <!-- 操作（后端反馈端点已删除 → 仅本地收藏） -->
            <div class="card-actions">
              <el-button
                :type="isFavorite(item) ? 'primary' : 'default'"
                size="small"
                :icon="isFavorite(item) ? StarFilled : Star"
                @click="toggleFavorite(item)"
              >
                {{ isFavorite(item) ? '已收藏' : '收藏' }}
              </el-button>
            </div>
          </div>
        </div>
      </div>

      <!-- 空结果提示 -->
      <div v-else-if="matchResult && matchResults.length === 0" class="no-results">
        <el-icon :size="40" color="var(--c-text-3)"><Opportunity /></el-icon>
        <p>暂无匹配结果，可放宽距离阈值后重试</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.matching-page {
  max-width: 1100px;
  margin: 0 auto;
}

/* 加载 & 空状态 */
.loading-container,
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 50vh;
  text-align: center;
  gap: var(--space-4);
}
.loading-container p,
.empty-state p {
  font-size: 14px;
  color: var(--c-text-3);
}
.empty-state h3 {
  font-size: 18px;
  font-weight: 600;
  color: var(--c-text-1);
  margin: 0;
}

/* 通用 Widget */
.widget {
  background: var(--c-surface);
  border-radius: var(--radius-md);
  padding: var(--space-5);
  border: 1px solid var(--c-bg-mute);
  box-shadow: var(--shadow-xs);
}
.widget-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-4);
}
.header-left {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.widget-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--c-text-1);
}
.profile-badge {
  padding: 2px 10px;
  border-radius: var(--radius-full);
  background: var(--c-brand-lighter);
  color: var(--c-brand);
  font-size: 12px;
  font-weight: 500;
}

/* 控制面板 */
.control-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.control-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-5);
}
.control-item {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.control-label {
  font-size: 13px;
  color: var(--c-text-2);
  font-weight: 500;
}
.control-value {
  font-size: 12px;
  color: var(--c-text-3);
  text-align: right;
}
.control-actions {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding-top: var(--space-3);
  border-top: 1px solid var(--c-bg-mute);
}
.control-hint {
  font-size: 12px;
  color: var(--c-text-3);
}

/* 结果区域 */
.results-section,
.history-section {
  margin-top: var(--space-5);
}
.section-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
}
.section-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--c-text-1);
}
.section-count {
  font-size: 12px;
  color: var(--c-text-3);
  margin-left: auto;
}

/* 结果卡片 Grid */
.results-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-5);
}
.result-card {
  background: var(--c-surface);
  border-radius: var(--radius-md);
  padding: var(--space-5);
  border: 1px solid var(--c-bg-mute);
  box-shadow: var(--shadow-xs);
  position: relative;
  transition: box-shadow var(--duration-fast) ease, transform var(--duration-fast) ease;
}
.result-card:hover {
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}
.result-card.top {
  border-color: var(--c-brand-lighter);
}

/* 排名标识 */
.rank-badge {
  position: absolute;
  top: -8px;
  left: -8px;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
  color: #fff;
  background: var(--c-text-3);
  box-shadow: var(--shadow-sm);
}
.rank-badge.rank-1 { background: linear-gradient(135deg, #f59e0b, #f97316); }
.rank-badge.rank-2 { background: linear-gradient(135deg, #94a3b8, #64748b); }
.rank-badge.rank-3 { background: linear-gradient(135deg, #b45309, #92400e); }

/* 卡片头部 */
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}
.job-title-row {
  flex: 1;
  min-width: 0;
}
.job-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--c-text-1);
  margin: 0 0 var(--space-2) 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.job-meta {
  display: flex;
  gap: var(--space-1);
  flex-wrap: wrap;
}

/* 匹配分数徽章 */
.match-score-badge {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  color: #fff;
  flex-shrink: 0;
}
.score-value {
  font-size: 16px;
  font-weight: 700;
  line-height: 1.2;
}
.score-label {
  font-size: 10px;
  opacity: 0.9;
  white-space: nowrap;
}

/* 岗位信息 */
.job-info {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--c-bg-mute);
}
.info-item {
  display: flex;
  align-items: center;
  gap: 4px;
}
.info-label {
  font-size: 12px;
  color: var(--c-text-3);
}
.info-value {
  font-size: 12px;
  color: var(--c-text-2);
  font-weight: 500;
}

/* 维度分析 */
.analysis-section {
  margin-bottom: var(--space-3);
}
.analysis-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-2);
}
.analysis-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--c-text-2);
}
.analysis-scores {
  display: flex;
  gap: var(--space-1);
}
.analysis-tag {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: var(--radius-sm);
}
.analysis-tag.vector {
  background: rgba(99, 102, 241, 0.1);
  color: #6366f1;
}
.analysis-tag.dimension {
  background: rgba(34, 197, 94, 0.1);
  color: #22c55e;
}

/* 维度匹配条 */
.dimension-bars {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.dim-bar-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.dim-name {
  width: 70px;
  font-size: 11px;
  color: var(--c-text-3);
  flex-shrink: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dim-bar-bg {
  flex: 1;
  height: 6px;
  background: var(--c-bg-soft);
  border-radius: var(--radius-full);
  overflow: hidden;
}
.dim-bar-fill {
  height: 100%;
  border-radius: var(--radius-full);
  transition: width 0.6s ease;
}
.dim-value {
  width: 40px;
  font-size: 11px;
  font-weight: 600;
  text-align: right;
  flex-shrink: 0;
}

/* 岗位摘要 */
.job-summary {
  font-size: 12px;
  color: var(--c-text-3);
  line-height: 1.5;
  margin-bottom: var(--space-3);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* 反馈操作 */
.card-actions {
  display: flex;
  gap: var(--space-1);
  flex-wrap: wrap;
  padding-top: var(--space-3);
  border-top: 1px solid var(--c-bg-mute);
}

/* 无结果 */
.no-results {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 150px;
  gap: var(--space-3);
  color: var(--c-text-3);
  font-size: 14px;
}

/* 历史记录 */
.history-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.history-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-3) var(--space-4);
  background: var(--c-surface);
  border-radius: var(--radius-sm);
  border: 1px solid var(--c-bg-mute);
}
.history-job {
  font-size: 13px;
  color: var(--c-text-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}
.history-score {
  font-size: 13px;
  font-weight: 600;
  flex-shrink: 0;
  margin-left: var(--space-3);
}

/* 响应式 */
@media (max-width: 768px) {
  .control-row {
    grid-template-columns: 1fr;
  }
  .results-grid {
    grid-template-columns: 1fr;
  }
  .dim-name {
    width: 55px;
  }
  .card-actions .el-button {
    flex: 1;
  }
}
</style>
