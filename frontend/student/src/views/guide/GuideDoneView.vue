<script setup lang="ts">
/**
 * 引导第 5 步（最后一步）：生成报告
 * 读取前两步留下的冻结缓存（匹配结果 + 主攻岗位），展示摘要后调用 POST /reports/generate。
 * 数据来源：localStorage 'guide.matching_results'（恰 3 项，match_score 为 0~1 比例）
 *          localStorage 'guide.selected_job'（{ job_profile_id, title }）
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh, Search } from '@element-plus/icons-vue'
import SectionCard from '@/components/SectionCard.vue'
import ScoreBadge from '@/components/ScoreBadge.vue'
import EmptyState from '@/components/EmptyState.vue'
import { reportApi, type MatchResultInput } from '@/api/report'
import { jobsApi } from '@/api/jobs'
import { profileApi, type SnapshotDetail } from '@/api/profile'
import { useJourneyStore } from '@/stores/journey'

/** 冻结契约：选岗步骤（step 3）写入的匹配结果 */
const MATCHING_RESULTS_KEY = 'guide.matching_results'
/** 冻结契约：策略步骤（step 4）写入的主攻岗位 */
const SELECTED_JOB_KEY = 'guide.selected_job'
/** 后端要求 matching_results 恰 3 项，否则 422 */
const REQUIRED_MATCH_COUNT = 3

interface SelectedJob {
  job_profile_id: number
  title: string
}

interface MatchRow {
  job_profile_id: number
  title: string
  percent: number   // 0-100，仅用于展示；提交后端时仍用原始 0~1 比例
  isPrimary: boolean
}

const router = useRouter()
const journey = useJourneyStore()

const loading = ref(true)
const generating = ref(false)
const error = ref('')
const snapshotMissing = ref(false)

const results = ref<MatchResultInput[]>([])
const selectedJob = ref<SelectedJob | null>(null)
const snapshot = ref<SnapshotDetail | null>(null)
const titles = ref<Record<number, string>>({})

/* ---------------- 缓存读取（每次读取独立 try/catch，损坏数据不炸页面） ---------------- */

function readMatchingResults(): MatchResultInput[] {
  try {
    const raw = localStorage.getItem(MATCHING_RESULTS_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as unknown
    if (!Array.isArray(parsed)) return []
    return parsed.reduce<MatchResultInput[]>((acc, item) => {
      if (!item || typeof item !== 'object') return acc
      const record = item as Record<string, unknown>
      const id = record.job_profile_id
      if (typeof id !== 'number' || !Number.isFinite(id)) return acc
      const score = Number(record.match_score)
      // match_score 原样保留（0~1 比例），后端要的就是它，不做百分比换算
      acc.push({ job_profile_id: id, match_score: Number.isFinite(score) ? score : 0 })
      return acc
    }, [])
  } catch {
    return []   // localStorage 不可用 / JSON 损坏 → 交给完整性守门处理
  }
}

function readSelectedJob(): SelectedJob | null {
  try {
    const raw = localStorage.getItem(SELECTED_JOB_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as unknown
    if (!parsed || typeof parsed !== 'object') return null
    const record = parsed as Record<string, unknown>
    const id = record.job_profile_id
    if (typeof id !== 'number' || !Number.isFinite(id)) return null
    return {
      job_profile_id: id,
      title: typeof record.title === 'string' ? record.title.trim() : '',
    }
  } catch {
    return null
  }
}

/* ---------------- 展示派生 ---------------- */

function toPercent(score: number): number {
  const value = Number(score)
  if (!Number.isFinite(value)) return 0
  return Math.min(100, Math.max(0, Math.round(value * 100)))
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '未获取'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value   // 非法时间串原样展示，不做假设
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** 主攻岗位 id：优先用 selected_job；缺失/对不上时回退到最高匹配分那一项 */
const primaryId = computed<number | null>(() => {
  const selected = selectedJob.value
  if (selected && results.value.some(item => item.job_profile_id === selected.job_profile_id)) {
    return selected.job_profile_id
  }
  let best: MatchResultInput | null = null
  for (const item of results.value) {
    if (!best || (Number(item.match_score) || 0) > (Number(best.match_score) || 0)) best = item
  }
  return best ? best.job_profile_id : null
})

const primaryFromSelection = computed(() => {
  const selected = selectedJob.value
  if (!selected) return false
  return results.value.some(item => item.job_profile_id === selected.job_profile_id)
})

function resolveTitle(id: number): string {
  const fetched = titles.value[id]
  if (fetched) return fetched
  const selected = selectedJob.value
  if (selected && selected.job_profile_id === id && selected.title) return selected.title
  return `岗位 #${id}`   // 岗位详情失败时的降级名
}

const rows = computed<MatchRow[]>(() => results.value.map(item => ({
  job_profile_id: item.job_profile_id,
  title: resolveTitle(item.job_profile_id),
  percent: toPercent(item.match_score),
  isPrimary: primaryId.value === item.job_profile_id,
})))

const primaryFallbackNote = computed(() => {
  if (!rows.value.length) return ''
  if (!selectedJob.value) return '未读取到主攻岗位选择，已按最高匹配分标记主攻岗位。'
  if (!primaryFromSelection.value) return '主攻岗位不在本次匹配结果中，已按最高匹配分标记主攻岗位。'
  return ''
})

/** 一句话定位：只使用已有数据，不引入任何额外事实 */
const positioning = computed(() => {
  const primary = rows.value.find(row => row.isPrimary)
  if (!primary) return ''
  const others = rows.value.length - 1
  return others > 0
    ? `以「${primary.title}」为主攻方向，同步准备另外 ${others} 个备选岗位。`
    : `以「${primary.title}」为主攻方向。`
})

const matchSubtitle = computed(() =>
  rows.value.length ? `共 ${rows.value.length} 个匹配岗位` : '暂无匹配结果')

const snapshotTime = computed(() => formatDateTime(snapshot.value?.created_at))
const snapshotSerial = computed(() => snapshot.value?.serial_no || '未获取')

/* ---------------- 加载 ---------------- */

async function loadTitles(): Promise<void> {
  const map: Record<number, string> = {}
  await Promise.all(results.value.map(async (item) => {
    try {
      const detail = await jobsApi.getDetail(item.job_profile_id)
      if (detail?.title) map[item.job_profile_id] = detail.title
    } catch {
      /* 单个岗位详情失败 → 由 resolveTitle 回退，不影响其余岗位 */
    }
  }))
  titles.value = map
}

async function loadSummary(): Promise<void> {
  loading.value = true
  try {
    results.value = readMatchingResults()
    selectedJob.value = readSelectedJob()
    // 直接落地本页（没经过欢迎页守卫）时 store 可能为空，补一次状态拉取；失败保持降级
    if (journey.snapshotId == null) {
      try {
        await journey.fetchStatus()
      } catch {
        /* 离线等场景忽略，摘要降级但仍可操作 */
      }
    }
    const snapshotId = journey.snapshotId
    if (snapshotId != null) {
      try {
        snapshot.value = await profileApi.getSnapshotDetail(snapshotId)
      } catch {
        snapshot.value = null   // 快照详情失败 → 摘要降级，绝不阻塞生成
      }
    }
    await loadTitles()
  } finally {
    loading.value = false
  }
}

onMounted(() => { void loadSummary() })

/* ---------------- 生成报告 ---------------- */

function extractDetail(err: unknown): string {
  const e = err as { response?: { data?: { detail?: unknown } } } | null
  const detail = e?.response?.data?.detail
  return typeof detail === 'string' && detail.trim() ? detail : ''
}

async function generate(): Promise<void> {
  if (generating.value) return
  error.value = ''
  snapshotMissing.value = false

  // 完整性守门：后端只接受恰 3 项，不满足时直接回选岗步骤，不发请求
  if (results.value.length !== REQUIRED_MATCH_COUNT) {
    ElMessage.warning('匹配数据缺失，请回到选岗步骤')
    router.push('/guide/match')
    return
  }

  // 防御：快照缺失时补拉一次状态
  if (journey.snapshotId == null) {
    try {
      await journey.fetchStatus()
    } catch {
      /* 离线等场景忽略，下面统一判空 */
    }
  }
  const snapshotId = journey.snapshotId
  if (snapshotId == null) {
    error.value = '缺少画像快照'
    snapshotMissing.value = true
    return
  }

  generating.value = true
  try {
    await reportApi.generateReport({
      profile_snapshot_id: snapshotId,
      matching_results: results.value,   // 原始 0~1 比例，恰 3 项
    })
    journey.markWelcomeSeen()
    journey.setGuideStep('done')
    try {
      await journey.fetchStatus()   // 与服务端对齐；失败不阻塞跳转
    } catch {
      /* 离线等场景忽略 */
    }
    ElMessage.success('报告已生成，进入成果区')
    router.push('/')
  } catch (err) {
    // api/request.ts 的响应拦截器已对非 401 错误统一 toast，
    // 这里只落内联错误，避免同一次失败被提示两次
    error.value = extractDetail(err) || '报告生成失败，请重试'
  } finally {
    generating.value = false
  }
}

function goMatch(): void {
  router.push('/guide/match')
}
</script>

<template>
  <div class="guide-page">
    <header class="page-head">
      <h2 class="guide-title">生成报告</h2>
      <p class="guide-desc">确认画像快照与选岗结果后，一键生成你的职业规划报告。</p>
    </header>

    <div v-if="loading" class="state-box">
      <el-icon class="is-loading" :size="24"><Refresh /></el-icon>
      <p class="state-text">正在读取选岗数据…</p>
    </div>

    <template v-else>
      <SectionCard title="画像快照" subtitle="报告将基于该快照生成">
        <div class="meta-grid">
          <div class="meta-item">
            <span class="meta-label">快照 ID</span>
            <span class="meta-value">{{ journey.snapshotId ?? '未获取' }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">创建时间</span>
            <span class="meta-value">{{ snapshotTime }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">快照编号</span>
            <span class="meta-value">{{ snapshotSerial }}</span>
          </div>
        </div>
        <p v-if="!snapshot" class="degraded-note">快照详情暂不可用，仍可继续生成报告。</p>
      </SectionCard>

      <SectionCard title="岗位匹配结果" :subtitle="matchSubtitle">
        <template v-if="rows.length">
          <ul class="match-list">
            <li
              v-for="row in rows"
              :key="row.job_profile_id"
              class="match-row"
              :class="{ 'is-primary': row.isPrimary }"
            >
              <ScoreBadge :score="row.percent" size="medium" show-label />
              <div class="match-main">
                <p class="match-title">
                  {{ row.title }}
                  <span v-if="row.isPrimary" class="primary-tag">主攻岗位</span>
                </p>
                <p class="match-sub">岗位 #{{ row.job_profile_id }} · 匹配度 {{ row.percent }}%</p>
              </div>
            </li>
          </ul>
          <p v-if="primaryFallbackNote" class="fallback-note">{{ primaryFallbackNote }}</p>
          <p class="positioning">{{ positioning }}</p>
        </template>

        <EmptyState
          v-else
          :icon="Search"
          title="还没有匹配结果"
          description="先回到选岗步骤完成岗位匹配，再回来生成报告。"
          show-action
          action-text="回到选岗步骤"
          @action="goMatch"
        />
      </SectionCard>

      <div v-if="error" class="error-box">
        <p class="error-text">{{ error }}</p>
        <router-link v-if="snapshotMissing" class="go-link" to="/guide/parse">回到画像解析</router-link>
      </div>

      <div class="generate-bar">
        <el-button
          type="primary"
          size="large"
          class="generate-btn hover-lift press-effect"
          :loading="generating"
          @click="generate"
        >
          生成报告
        </el-button>
        <p class="generate-hint">生成后可在成果区查看并下载报告全文。</p>
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

/* 快照摘要 */
.meta-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-3);
}
.meta-item {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-3) var(--space-4);
  background: var(--c-bg-soft);
  border-radius: var(--radius-md);
}
.meta-label {
  font-size: var(--text-xs);
  color: var(--c-text-3);
}
.meta-value {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--c-text-1);
  word-break: break-all;
}
.degraded-note {
  margin: var(--space-3) 0 0;
  font-size: var(--text-xs);
  color: var(--c-warning);
}

/* 岗位列表 */
.match-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin: 0;
  padding: 0;
}
.match-row {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-4);
  background: var(--c-bg-soft);
  border: 1px solid var(--c-bg-mute);
  border-radius: var(--radius-lg);
  transition: box-shadow 0.2s ease;
}
.match-row:hover {
  box-shadow: var(--shadow-sm);
}
.match-row.is-primary {
  background: var(--c-brand-lighter);
}
.match-main {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  min-width: 0;
}
.match-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0;
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--c-text-1);
}
.primary-tag {
  flex-shrink: 0;
  padding: 0 var(--space-2);
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--c-brand);
  background: var(--c-surface);
  border-radius: var(--radius-full);
}
.match-sub {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--c-text-3);
}
.fallback-note {
  margin: var(--space-3) 0 0;
  font-size: var(--text-xs);
  color: var(--c-warning);
}
.positioning {
  margin: var(--space-4) 0 0;
  padding-top: var(--space-4);
  border-top: 1px solid var(--c-bg-mute);
  font-size: var(--text-sm);
  color: var(--c-text-2);
  line-height: 1.7;
}

/* 错误 / 生成区 */
.error-box {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-3) var(--space-4);
  background: var(--c-bg-soft);
  border: 1px solid var(--c-bg-mute);
  border-radius: var(--radius-md);
}
.error-text {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--c-danger);
}
.generate-bar {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) 0 var(--space-4);
}
.generate-btn {
  min-width: 220px;
  border-radius: var(--radius-full);
  font-weight: 600;
}
.generate-hint {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--c-text-3);
}
.go-link {
  flex-shrink: 0;
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--c-brand);
  text-decoration: none;
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-full);
  background: var(--c-brand-lighter);
  transition: opacity 0.2s ease;
}
.go-link:hover {
  opacity: 0.85;
}

@media (max-width: 768px) {
  .guide-title {
    font-size: 22px;
  }
  .meta-grid {
    grid-template-columns: 1fr;
  }
}
</style>
