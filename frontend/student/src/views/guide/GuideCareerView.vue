<script setup lang="ts">
/**
 * 引导第 4 步：匹配策略 —— 主攻岗位确认
 * 契约（冻结）：
 * - 读 localStorage 'guide.matching_results' = [{ job_profile_id, match_score }]，恰 3 项，match_score 为 0~1
 * - 写 localStorage 'guide.selected_job' = { job_profile_id, title }，供第 5 步 GuideDoneView 读取
 * 缺失 / 解析失败 / 非数组 / 长度非 3 → 提示并回退到选岗页，绝不渲染破损页面。
 */
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import SectionCard from '@/components/SectionCard.vue'
import ScoreBadge from '@/components/ScoreBadge.vue'
import DimensionBar from '@/components/DimensionBar.vue'
import { jobsApi, type JobProfileResponse } from '@/api/jobs'
import { useJourneyStore } from '@/stores/journey'

const MATCHING_KEY = 'guide.matching_results'
const SELECTED_KEY = 'guide.selected_job'

/** 仅取第 3 步契约保证存在的两个字段，结构上兼容多余键（analysis 等） */
interface MatchItem {
  job_profile_id: number
  match_score: number
}

interface DimensionRow {
  dimKey: string
  detail: {
    user_score: number
    job_score: number
    match_ratio: number
  }
}

const router = useRouter()
const journey = useJourneyStore()

const loading = ref(true)
const ready = ref(false)
const selectedId = ref<number | null>(null)
const matches = ref<MatchItem[]>([])
/** 详情逐个 try/catch，失败落 null，页面降级而不是空白 */
const details = ref<Record<number, JobProfileResponse | null>>({})

function isRecord(value: unknown): value is Record<string, any> {
  return typeof value === 'object' && value !== null
}

/** 读 + 校验选岗结果；任何异常都返回 null 交给调用方回退 */
function readMatchingResults(): MatchItem[] | null {
  try {
    const raw = localStorage.getItem(MATCHING_KEY)
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed) || parsed.length !== 3) return null
    const items: MatchItem[] = []
    for (const row of parsed) {
      if (!isRecord(row)) return null
      const id = Number(row.job_profile_id)
      if (!Number.isFinite(id)) return null
      const score = Number(row.match_score)
      items.push({ job_profile_id: id, match_score: Number.isFinite(score) ? score : 0 })
    }
    return items
  } catch {
    return null
  }
}

function titleOf(jobProfileId: number): string {
  return details.value[jobProfileId]?.title ?? `岗位 #${jobProfileId}`
}

/** 唯一的写入口：选择变化与默认选中/详情补全后都调用它 */
function persistSelection() {
  const id = selectedId.value
  if (id == null) return
  const title = details.value[id]?.title ?? ''
  try {
    localStorage.setItem(SELECTED_KEY, JSON.stringify({ job_profile_id: id, title }))
  } catch {
    /* localStorage 不可用时忽略，不阻塞交互 */
  }
}

function selectJob(jobProfileId: number) {
  if (selectedId.value === jobProfileId) return
  selectedId.value = jobProfileId
  persistSelection()
}

/** 单选语义 + 键盘可达性 */
function onCardKeydown(event: KeyboardEvent, jobProfileId: number) {
  if (event.key === 'Enter' || event.key === ' ' || event.key === 'Spacebar') {
    event.preventDefault()
    selectJob(jobProfileId)
  }
}

async function loadDetails(items: MatchItem[]): Promise<void> {
  const map: Record<number, JobProfileResponse | null> = {}
  await Promise.all(
    items.map(async (item) => {
      try {
        map[item.job_profile_id] = await jobsApi.getDetail(item.job_profile_id)
      } catch {
        map[item.job_profile_id] = null   // 单个岗位详情失败 → 降级展示，不影响整页
      }
    }),
  )
  details.value = map
}

async function bootstrap(): Promise<void> {
  loading.value = true
  const items = readMatchingResults()
  if (!items) {
    loading.value = false
    ElMessage.warning('匹配数据缺失，请重新选岗')
    await router.replace('/guide/match')
    return
  }
  matches.value = items
  // 默认选中第一项（重进本页时保留用户已有的选择）
  selectedId.value = readExistingSelection() ?? items[0].job_profile_id
  persistSelection()                       // 立即写入，避免首次「下一步」时 key 尚不存在
  try {
    await loadDetails(items)
  } catch {
    details.value = {}                     // 兜底：详情整体异常也保留列表
  }
  persistSelection()                       // 详情到位后补全 title
  ready.value = true
  loading.value = false
}

/** 已存在的 guide.selected_job 只在仍属于本次匹配结果时复用 */
function readExistingSelection(): number | null {
  try {
    const raw = localStorage.getItem(SELECTED_KEY)
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    if (!isRecord(parsed)) return null
    const id = Number(parsed.job_profile_id)
    if (!Number.isFinite(id)) return null
    return matches.value.some(m => m.job_profile_id === id) ? id : null
  } catch {
    return null
  }
}

onMounted(() => { void bootstrap() })

function scorePercent(matchScore: number): number {
  return Math.round((Number.isFinite(matchScore) ? matchScore : 0) * 100)
}

function ratioPercent(matchRatio: unknown): string {
  const ratio = Number(matchRatio)
  return `${Math.round((Number.isFinite(ratio) ? ratio : 0) * 100)}%`
}

/** m.analysis 可能整体缺失 → 全部走可选链 */
function dimensionRows(item: MatchItem): DimensionRow[] {
  const analysis = (item as { analysis?: { dimension_matches?: Record<string, any> } }).analysis
  const dimensionMatches = analysis?.dimension_matches
  if (!isRecord(dimensionMatches)) return []
  const rows: DimensionRow[] = []
  for (const [dimKey, raw] of Object.entries(dimensionMatches)) {
    const detail = isRecord(raw) ? raw : {}
    rows.push({
      dimKey,
      detail: {
        user_score: Number(detail.user_score) || 0,
        job_score: Number(detail.job_score) || 0,
        match_ratio: Number(detail.match_ratio) || 0,
      },
    })
  }
  return rows
}

function confirmStrategy(): void {
  if (selectedId.value == null) return
  persistSelection()
  journey.setGuideStep('done')
  void router.push('/guide/done')
}
</script>

<template>
  <div class="guide-page">
    <header class="page-head">
      <h2 class="guide-title">匹配策略</h2>
      <p class="guide-desc">
        以下 3 个岗位来自你的画像匹配结果，请选择 1 个作为主攻方向，后续策略与报告都会围绕它展开。
      </p>
    </header>

    <div v-if="loading" class="state-box">
      <el-icon class="is-loading" :size="24"><Refresh /></el-icon>
      <p class="state-text">正在加载匹配结果…</p>
    </div>

    <template v-else-if="ready">
      <SectionCard title="选择主攻岗位" subtitle="单选" no-padding>
        <div class="job-list" role="radiogroup" aria-label="主攻岗位">
          <div
            v-for="m in matches"
            :key="m.job_profile_id"
            class="job-card"
            :class="{ 'is-checked': selectedId === m.job_profile_id }"
            role="radio"
            :aria-checked="selectedId === m.job_profile_id"
            :tabindex="selectedId === m.job_profile_id ? 0 : -1"
            @click="selectJob(m.job_profile_id)"
            @keydown="onCardKeydown($event, m.job_profile_id)"
          >
            <div class="job-head">
              <el-checkbox
                class="job-check"
                :model-value="selectedId === m.job_profile_id"
                @change="selectJob(m.job_profile_id)"
                @click.stop
              />
              <h3 class="job-title">{{ titleOf(m.job_profile_id) }}</h3>
              <ScoreBadge
                :score="scorePercent(m.match_score)"
                size="medium"
                show-label
              />
            </div>

            <p
              v-if="details[m.job_profile_id]?.summary"
              class="job-summary"
            >
              {{ details[m.job_profile_id]?.summary }}
            </p>

            <div
              v-if="details[m.job_profile_id]?.industry
                || details[m.job_profile_id]?.level
                || details[m.job_profile_id]?.salary_range
                || details[m.job_profile_id]?.education_requirement"
              class="job-meta"
            >
              <span v-if="details[m.job_profile_id]?.industry" class="meta-item">
                {{ details[m.job_profile_id]?.industry }}
              </span>
              <span v-if="details[m.job_profile_id]?.level" class="meta-item">
                {{ details[m.job_profile_id]?.level }}
              </span>
              <span v-if="details[m.job_profile_id]?.salary_range" class="meta-item">
                {{ details[m.job_profile_id]?.salary_range }}
              </span>
              <span v-if="details[m.job_profile_id]?.education_requirement" class="meta-item">
                {{ details[m.job_profile_id]?.education_requirement }}
              </span>
            </div>

            <div v-if="dimensionRows(m).length" class="job-dims">
              <div
                v-for="row in dimensionRows(m)"
                :key="row.dimKey"
                class="dim-row"
              >
                <DimensionBar
                  :label="row.dimKey"
                  :value="row.detail.user_score"
                  :max="Math.max(row.detail.job_score, row.detail.user_score, 0.01)"
                  :show-value="false"
                />
                <span class="dim-ratio">{{ ratioPercent(row.detail.match_ratio) }}</span>
              </div>
            </div>
            <p v-else class="job-dims-empty">该岗位暂无维度对比数据</p>
          </div>
        </div>
      </SectionCard>

      <div class="confirm-bar">
        <el-button
          type="primary"
          size="large"
          class="confirm-btn hover-lift press-effect"
          :disabled="selectedId == null"
          @click="confirmStrategy"
        >
          确定策略
        </el-button>
      </div>
    </template>
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

/* 岗位对比列表 */
.job-list {
  display: flex;
  flex-direction: column;
}
.job-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-5);
  cursor: pointer;
  background: var(--c-surface);
  border: 1px solid transparent;
  border-bottom-color: var(--c-bg-mute);
  transition: background-color 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
}
.job-card:last-child {
  border-bottom-color: transparent;
}
.job-card:hover {
  background: var(--c-bg-soft);
}
.job-card.is-checked {
  background: var(--c-brand-lighter);
  border-color: var(--c-brand);
  box-shadow: var(--shadow-sm);
}
.job-card:focus-visible {
  outline: none;
  border-color: var(--c-brand);
}
.job-head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.job-check {
  flex-shrink: 0;
}
.job-title {
  flex: 1;
  min-width: 0;
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--c-text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.job-summary {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--c-text-2);
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.job-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2) var(--space-3);
}
.meta-item {
  font-size: var(--text-xs);
  color: var(--c-text-3);
  background: var(--c-bg-soft);
  border: 1px solid var(--c-bg-mute);
  border-radius: var(--radius-full);
  padding: 2px var(--space-2);
}
.job-card.is-checked .meta-item {
  background: var(--c-surface);
}
.job-dims {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.dim-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.dim-row :deep(.dimension-bar) {
  flex: 1;
  min-width: 0;
}
.dim-ratio {
  flex-shrink: 0;
  width: 40px;
  text-align: right;
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--c-text-2);
}
.job-dims-empty {
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
  .job-card {
    padding: var(--space-4);
  }
}
</style>
