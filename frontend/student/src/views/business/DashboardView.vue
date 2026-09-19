<script setup lang="ts">
/**
 * 业务区总览（Task 13）
 * 数据源：GET /reports/records、GET /profile/snapshots(+detail)、GET /journey/status
 * 结构：4 张统计卡 + 最新报告片段 + 历史列（画像版本 / 报告版本）+ 操作按钮组
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Document,
  Files,
  Notebook,
  Briefcase,
  Refresh,
  WarningFilled,
} from '@element-plus/icons-vue'
import DashboardStatCard from '@/components/DashboardStatCard.vue'
import SectionCard from '@/components/SectionCard.vue'
import EmptyState from '@/components/EmptyState.vue'
import { reportApi, type ReportRecord } from '@/api/report'
import { profileApi, type SnapshotSummary, type SnapshotDetail } from '@/api/profile'
import { useJourneyStore } from '@/stores/journey'

/** 五层键：用于估算画像完成度 */
const LAYER_KEYS = ['intention', 'traits', 'practice', 'soft_skills', 'hard_skills'] as const
/** 报告片段截断长度（计划：report_text 前 ~300 字） */
const REPORT_SNIPPET_MAX = 300

const router = useRouter()
const journey = useJourneyStore()

const loading = ref(true)
const error = ref('')
const records = ref<ReportRecord[]>([])
const snapshots = ref<SnapshotSummary[]>([])
const latestText = ref('')
const snippetLoading = ref(false)

interface LayerCount {
  filled: number
  total: number
}

/** 当前画像五层填充情况（按后端冻结的 five_layers 逐层判定非空） */
const layerCount = ref<LayerCount | null>(null)

/** 画像完成度：已填充层数 / 5；无快照时 null（显示占位） */
const completeness = computed<number | null>(() => {
  if (!layerCount.value) return null
  return Math.round((layerCount.value.filled / layerCount.value.total) * 100)
})

/** 版本计数以 store（/journey/status）为准，接口未返回时回落到列表长度 */
const reportVersionCount = computed(() => journey.reportVersions || records.value.length)
const snapshotCount = computed(() => snapshots.value.length)

const latestRecord = computed<ReportRecord | null>(() => records.value[0] ?? null)

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** serial_no 短码（uuid 前 8 位） */
function shortSerial(serial: string | null | undefined): string {
  return serial ? String(serial).slice(0, 8) : '—'
}

/** 每层是否有内容（对象看键数量；数组/字符串看长度） */
function isLayerFilled(value: unknown): boolean {
  if (value == null) return false
  if (typeof value === 'string') return value.trim().length > 0
  if (Array.isArray(value)) return value.length > 0
  if (typeof value === 'object') {
    return Object.values(value as Record<string, unknown>).some(v => isLayerFilled(v))
  }
  return true
}

function countLayers(detail: SnapshotDetail): LayerCount {
  const layers = detail.five_layers ?? {}
  const filled = LAYER_KEYS.filter(k => isLayerFilled(layers[k])).length
  return { filled, total: LAYER_KEYS.length }
}

async function loadSnippet(): Promise<void> {
  const latest = latestRecord.value
  if (!latest) {
    latestText.value = ''
    return
  }
  snippetLoading.value = true
  try {
    const detail = await reportApi.getRecord(latest.id)
    const text = (detail.report_text || '').trim()
    latestText.value = text.slice(0, REPORT_SNIPPET_MAX)
  } catch {
    latestText.value = ''   // 片段失败不影响其余区块
  } finally {
    snippetLoading.value = false
  }
}

async function loadDashboard(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    // 三个数据源相互独立：单个失败不应让整页空白
    const [recRes, snapRes] = await Promise.allSettled([
      reportApi.getRecords(),
      profileApi.getSnapshots(),
    ])
    records.value = recRes.status === 'fulfilled' ? recRes.value : []
    snapshots.value = snapRes.status === 'fulfilled' ? snapRes.value : []
    if (recRes.status === 'rejected' && snapRes.status === 'rejected') {
      error.value = '总览数据加载失败，请稍后重试'
    }

    try {
      await journey.fetchStatus()
    } catch {
      /* 离线等场景忽略：统计卡回落到列表长度 */
    }

    const latestSnap = snapshots.value[0]
    if (latestSnap) {
      try {
        layerCount.value = countLayers(await profileApi.getSnapshotDetail(latestSnap.id))
      } catch {
        layerCount.value = null
      }
    } else {
      layerCount.value = null
    }

    await loadSnippet()
  } finally {
    loading.value = false
  }
}

onMounted(() => { void loadDashboard() })

function goAllReports(): void {
  router.push('/career')
}

function goToGuide(): void {
  journey.setGuideStep('resume')
  router.push('/guide/resume')
}

function reload(): void {
  ElMessage.info('正在刷新总览数据')
  void loadDashboard()
}
</script>

<template>
  <div class="dashboard">
    <header class="dash-head">
      <div>
        <h2 class="dash-title">总览</h2>
        <p class="dash-desc">你的画像、匹配与报告一览。</p>
      </div>
      <el-button class="hover-lift" :icon="Refresh" @click="reload">刷新</el-button>
    </header>

    <div v-if="loading" class="state-box">
      <el-icon class="is-loading" :size="24"><Refresh /></el-icon>
      <p class="state-text">正在加载总览数据…</p>
    </div>

    <template v-else>
      <p v-if="error" class="error-note">
        <el-icon><WarningFilled /></el-icon>
        <span>{{ error }}</span>
      </p>

      <div class="stat-grid">
        <DashboardStatCard
          label="简历完成度"
          :value="completeness == null ? '—' : completeness"
          :suffix="completeness == null ? '' : '%'"
          :icon="Document"
          :hint="layerCount ? `五层画像已填 ${layerCount.filled}/${layerCount.total} 层` : '暂无画像快照'"
          :muted="completeness == null"
        />
        <DashboardStatCard
          label="画像快照数"
          :value="snapshotCount"
          suffix="个"
          :icon="Files"
          hint="每次画像冻结一份快照"
        />
        <DashboardStatCard
          label="报告版本数"
          :value="reportVersionCount"
          suffix="版"
          :icon="Notebook"
          hint="生成报告会新增一个版本"
        />
        <DashboardStatCard
          label="最近匹配岗位数"
          value="—"
          :icon="Briefcase"
          hint="匹配记录待接入（暂无接口持久化该数据）"
          muted
        />
      </div>

      <div class="dash-body">
        <div class="dash-main">
          <SectionCard
            title="最新报告"
            :subtitle="latestRecord ? `第 ${latestRecord.version} 版 · ${formatDateTime(latestRecord.created_at)}` : ''"
          >
            <template #header>
              <el-button v-if="latestRecord" link type="primary" @click="goAllReports">
                查看全部 →
              </el-button>
            </template>

            <div v-if="snippetLoading" class="snippet-loading">正在读取报告正文…</div>
            <p v-else-if="latestText" class="report-snippet">{{ latestText }}…</p>
            <EmptyState
              v-else
              title="还没有报告"
              description="完成画像确认与岗位匹配后即可生成第一份职业规划报告。"
            />
          </SectionCard>

          <div class="action-bar">
            <el-button type="primary" class="hover-lift press-effect" @click="goAllReports">
              查看全部报告
            </el-button>
            <el-button class="hover-lift" @click="goToGuide">重新引导</el-button>
          </div>
        </div>

        <aside class="dash-side">
          <SectionCard title="画像版本" :subtitle="`共 ${snapshotCount} 个`">
            <ul v-if="snapshots.length" class="history-list">
              <li v-for="s in snapshots" :key="s.id" class="history-item">
                <span class="history-dot" aria-hidden="true"></span>
                <span class="history-main">
                  <span class="history-code">{{ shortSerial(s.serial_no) }}</span>
                  <span class="history-time">{{ formatDateTime(s.created_at) }}</span>
                </span>
              </li>
            </ul>
            <p v-else class="history-empty">暂无快照</p>
          </SectionCard>

          <SectionCard title="报告版本" :subtitle="`共 ${records.length} 份`">
            <ul v-if="records.length" class="history-list">
              <li v-for="r in records" :key="r.id" class="history-item">
                <span class="history-dot" aria-hidden="true"></span>
                <span class="history-main">
                  <span class="history-code">v{{ r.version }} · {{ shortSerial(r.serial_no) }}</span>
                  <span class="history-time">{{ formatDateTime(r.created_at) }}</span>
                </span>
              </li>
            </ul>
            <p v-else class="history-empty">暂无报告</p>
          </SectionCard>
        </aside>
      </div>
    </template>
  </div>
</template>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

/* 页头 */
.dash-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
}
.dash-title {
  margin: 0 0 var(--space-2);
  font-family: var(--font-display);
  font-size: 28px;
  font-weight: 600;
  color: var(--c-text-1);
}
.dash-desc {
  margin: 0;
  font-size: var(--text-base);
  color: var(--c-text-2);
}

/* 状态区 */
.state-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  min-height: 240px;
  background: var(--c-surface);
  border: 1px solid var(--c-bg-mute);
  border-radius: var(--radius-lg);
  color: var(--c-text-3);
}
.state-text {
  margin: 0;
  font-size: var(--text-sm);
}
.error-note {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0;
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--c-bg-mute);
  border-radius: var(--radius-md);
  background: var(--c-bg-soft);
  color: var(--c-danger);
  font-size: var(--text-sm);
}

/* 统计卡 */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-4);
}

/* 主体两列 */
.dash-body {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
  gap: var(--space-5);
  align-items: start;
}
.dash-main {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  min-width: 0;
}
.dash-side {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  min-width: 0;
}

/* 报告片段 */
.snippet-loading {
  font-size: var(--text-sm);
  color: var(--c-text-3);
}
.report-snippet {
  margin: 0;
  font-size: var(--text-sm);
  line-height: 1.9;
  color: var(--c-text-2);
  white-space: pre-wrap;
  word-break: break-word;
}
.action-bar {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
}

/* 历史列表 */
.history-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
}
.history-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--c-bg-soft);
}
.history-dot {
  flex: none;
  width: 6px;
  height: 6px;
  border-radius: var(--radius-full);
  background: var(--c-brand);
}
.history-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.history-code {
  font-size: var(--text-sm);
  color: var(--c-text-1);
  word-break: break-all;
}
.history-time {
  font-size: var(--text-xs);
  color: var(--c-text-3);
}
.history-empty {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--c-text-3);
}

@media (max-width: 1024px) {
  .stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .dash-body {
    grid-template-columns: minmax(0, 1fr);
  }
}
@media (max-width: 640px) {
  .stat-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
