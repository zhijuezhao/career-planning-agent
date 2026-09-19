<script setup lang="ts">
/**
 * 职业报告页面（Task 16 迁移：旧 /reports 契约 → 新 records 契约）
 * 调用的后端API：
 *   - GET  /api/v1/journey/status                取最新快照 id（生成报告的入参）
 *   - POST /api/v1/reports/generate              生成报告记录（需 profile_snapshot_id + 恰 3 项匹配结果）
 *   - GET  /api/v1/reports/records               报告记录列表（无 body 文本）
 *   - GET  /api/v1/reports/records/{rid}         报告记录详情（含 report_text）
 *   - GET  /api/v1/reports/records/{rid}/download 惰性生成并下载 Word
 * 说明：旧契约的 `target_job` 输入在 records 契约中已不存在，改为对报告「描述」的本地筛选；
 *       generation 需要的 3 项匹配结果取自引导流程留下的 localStorage。
 */
import { ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Document,
  Loading,
  Warning,
  Promotion,
  Download,
  View,
  Clock,
  Files,
  DataAnalysis,
} from '@element-plus/icons-vue'
import ReportMarkdown from '@/components/ReportMarkdown.vue'
import { reportApi, type ReportRecord, type ReportRecordDetail } from '../../api/report'
import { useJourneyStore } from '../../stores/journey'

/** 引导流程写入的匹配结果键（guards/GuideMatchView 契约） */
const MATCHING_RESULTS_KEY = 'guide.matching_results'
/** 后端要求恰 3 项，否则 422 */
const REQUIRED_MATCH_COUNT = 3

// ==================== 状态 ====================

const journey = useJourneyStore()
const loading = ref(false)
const generating = ref(false)
const reportList = ref<ReportRecord[]>([])
const activeReport = ref<ReportRecordDetail | null>(null)
const selectedId = ref<number | null>(null)

/** 生成报告时的匹配结果（来自引导流程 localStorage） */
interface MatchInput {
  job_profile_id: number
  match_score: number
}

/** 本地筛选关键词（替代旧契约的 target_job 输入） */
const filterKeyword = ref('')

// ==================== 计算属性 ====================

/** 有画像快照才能生成报告（快照 id 来自 journey store） */
const hasProfile = computed(() => journey.snapshotId != null)
const profileId = computed(() => journey.snapshotId)

/** 报告正文（records 契约下是纯文本 report_text） */
const reportText = computed(() => activeReport.value?.report_text ?? '')

const filteredList = computed(() => {
  const kw = filterKeyword.value.trim()
  if (!kw) return reportList.value
  return reportList.value.filter(r => (r.description || '').includes(kw))
})

// ==================== 方法 ====================

/** 读取引导流程留下的匹配结果；不满足恰 3 项时返回 null */
function readMatchingResults(): MatchInput[] | null {
  try {
    const raw = localStorage.getItem(MATCHING_RESULTS_KEY)
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return null
    const items = parsed
      .filter((x): x is Record<string, unknown> => !!x && typeof x === 'object')
      .map(x => ({ job_profile_id: Number(x.job_profile_id), match_score: Number(x.match_score) }))
      .filter(x => Number.isFinite(x.job_profile_id) && Number.isFinite(x.match_score))
    return items.length === REQUIRED_MATCH_COUNT ? items : null
  } catch {
    return null
  }
}

async function loadReports() {
  try {
    reportList.value = await reportApi.getRecords()
    const first = reportList.value[0]
    if (first && selectedId.value == null) {
      await selectReport(first)
    }
  } catch {
    // 加载失败不影响其余区块
  }
}

async function selectReport(record: ReportRecord) {
  selectedId.value = record.id
  try {
    activeReport.value = await reportApi.getRecord(record.id)
  } catch {
    activeReport.value = null
    ElMessage.error('报告详情加载失败')
  }
}

async function generateReport() {
  if (profileId.value == null) {
    ElMessage.warning('请先上传简历并完成解析，生成画像快照')
    return
  }
  const matching = readMatchingResults()
  if (!matching) {
    ElMessage.warning('缺少匹配结果（需先完成选岗），请回到引导流程重新匹配')
    return
  }

  generating.value = true
  try {
    const result = await reportApi.generateReport({
      profile_snapshot_id: profileId.value,
      matching_results: matching,
    })
    ElMessage.success('报告生成成功')
    selectedId.value = result.id
    activeReport.value = result
    await loadReports()
    filterKeyword.value = ''
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '报告生成失败')
  } finally {
    generating.value = false
  }
}

async function downloadReport(record: ReportRecord) {
  try {
    const blob = await reportApi.downloadWord(record.id)
    const downloadUrl = URL.createObjectURL(blob as Blob)
    const link = document.createElement('a')
    link.href = downloadUrl
    link.download = `生涯发展报告_v${record.version}_${String(record.serial_no).slice(0, 8)}.docx`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(downloadUrl)
    ElMessage.success('下载已开始')
    // 惰性生成后后端回填 word_file_path
    if (selectedId.value === record.id) await selectReport(record)
  } catch {
    ElMessage.error('下载失败，请重试')
  }
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// ==================== 生命周期 ====================

onMounted(async () => {
  loading.value = true
  try {
    await journey.fetchStatus()
  } catch {
    // 离线等场景忽略：hasProfile 会回落到 false
  }
  await loadReports()
  loading.value = false
})
</script>

<template>
  <div class="report-page">
    <!-- 加载状态 -->
    <div v-if="loading" class="loading-container">
      <el-icon :size="32" class="is-loading" color="var(--c-brand)"><Loading /></el-icon>
      <p>正在加载报告数据...</p>
    </div>

    <!-- 空状态：无画像 -->
    <div v-else-if="!hasProfile" class="empty-state">
      <el-icon :size="48" color="var(--c-text-3)"><Warning /></el-icon>
      <h3>暂无能力画像</h3>
      <p>请先上传简历并完成解析，才能生成职业报告</p>
      <el-button type="primary" @click="$router.push('/resume')">前往上传简历</el-button>
    </div>

    <!-- 主要内容 -->
    <div v-else class="report-content">
      <!-- 生成报告面板 -->
      <div class="widget generate-panel">
        <div class="widget-header">
          <div class="header-left">
            <el-icon :size="18" color="var(--c-brand)"><Document /></el-icon>
            <span class="widget-title">生成职业报告</span>
          </div>
          <span class="profile-badge">画像 #{{ profileId }}</span>
        </div>
        <div class="generate-body">
          <div class="input-row">
            <el-input
              v-model="filterKeyword"
              placeholder="按报告描述筛选（如：第1版）"
              clearable
              :prefix-icon="DataAnalysis"
              style="flex: 1"
            />
            <el-button
              type="primary"
              :loading="generating"
              :icon="Promotion"
              @click="generateReport"
            >
              {{ generating ? '生成中...' : '生成报告' }}
            </el-button>
          </div>
          <p class="generate-hint">
            基于你的能力画像与最近一次选岗结果（恰 3 个岗位），AI 将生成含能力分析、职业建议、技能差距、行动计划六模块报告
          </p>
        </div>
      </div>

      <!-- 报告主体区域 -->
      <div class="report-main">
        <!-- 左侧报告列表 -->
        <div class="report-sidebar">
          <div class="sidebar-header">
            <el-icon :size="14"><Files /></el-icon>
            <span>报告列表</span>
            <span class="count-badge">{{ filteredList.length }}</span>
          </div>
          <div v-if="filteredList.length === 0" class="no-reports">
            <p>暂无报告</p>
          </div>
          <div v-else class="report-list">
            <div
              v-for="report in filteredList"
              :key="report.id"
              class="report-list-item"
              :class="{ active: selectedId === report.id }"
              @click="selectReport(report)"
            >
              <div class="item-header">
                <span class="item-title">第 {{ report.version }} 版</span>
                <el-tag size="small" effect="plain">
                  {{ String(report.serial_no).slice(0, 8) }}
                </el-tag>
              </div>
              <div class="item-meta">
                <span v-if="report.description" class="item-target">{{ report.description }}</span>
                <span class="item-date">
                  <el-icon :size="10"><Clock /></el-icon>
                  {{ formatDate(report.created_at) }}
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- 右侧报告内容 -->
        <div class="report-detail">
          <!-- 无选中报告 -->
          <div v-if="!activeReport" class="no-selection">
            <el-icon :size="40" color="var(--c-text-3)"><Document /></el-icon>
            <p>请从左侧选择一份报告，或生成一份新报告</p>
          </div>

          <!-- 报告内容 -->
          <div v-else class="report-viewer">
            <!-- 报告头部 -->
            <div class="report-viewer-header">
              <div class="viewer-title-row">
                <h2>生涯发展报告</h2>
                <div class="viewer-tags">
                  <el-tag v-if="activeReport.description" size="small" effect="plain" type="primary">
                    {{ activeReport.description }}
                  </el-tag>
                  <el-tag size="small" effect="plain">v{{ activeReport.version || 1 }}</el-tag>
                </div>
              </div>
              <div class="viewer-actions">
                <span class="viewer-date">{{ formatDate(activeReport.created_at) }}</span>
                <el-button
                  type="primary"
                  size="small"
                  :icon="Download"
                  @click="downloadReport(activeReport)"
                >
                  下载 Word
                </el-button>
              </div>
            </div>

            <!-- 报告正文（records 契约：report_text 纯文本，交 ReportMarkdown 渲染） -->
            <div v-if="reportText" class="report-body">
              <ReportMarkdown :text="reportText" />
            </div>

            <!-- 无内容 -->
            <div v-else class="no-content">
              <el-icon :size="36" color="var(--c-text-3)"><View /></el-icon>
              <p>报告内容正在生成中，请稍后刷新查看</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.report-page {
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

/* 生成面板 */
.generate-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.input-row {
  display: flex;
  gap: var(--space-3);
  align-items: center;
}
.generate-hint {
  font-size: 12px;
  color: var(--c-text-3);
  line-height: 1.5;
  margin: 0;
}

/* 报告主区域 */
.report-main {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: var(--space-5);
  margin-top: var(--space-5);
}

/* 侧边栏 */
.report-sidebar {
  background: var(--c-surface);
  border-radius: var(--radius-md);
  border: 1px solid var(--c-bg-mute);
  box-shadow: var(--shadow-xs);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  max-height: 600px;
}
.sidebar-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-4);
  border-bottom: 1px solid var(--c-bg-mute);
  font-size: 13px;
  font-weight: 600;
  color: var(--c-text-1);
}
.count-badge {
  margin-left: auto;
  font-size: 11px;
  padding: 1px 8px;
  border-radius: var(--radius-full);
  background: var(--c-brand-lighter);
  color: var(--c-brand);
}
.no-reports {
  padding: var(--space-6);
  text-align: center;
  font-size: 13px;
  color: var(--c-text-3);
}
.report-list {
  overflow-y: auto;
  flex: 1;
}
.report-list-item {
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--c-bg-mute);
  cursor: pointer;
  transition: background var(--duration-fast) ease;
}
.report-list-item:hover {
  background: var(--c-bg-soft);
}
.report-list-item.active {
  background: var(--c-brand-lighter);
  border-left: 3px solid var(--c-brand);
}
.item-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-1);
}
.item-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--c-text-1);
}
.item-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.item-target {
  font-size: 12px;
  color: var(--c-text-2);
}
.item-date {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--c-text-3);
}

/* 报告详情 */
.report-detail {
  background: var(--c-surface);
  border-radius: var(--radius-md);
  border: 1px solid var(--c-bg-mute);
  box-shadow: var(--shadow-xs);
  overflow: hidden;
  min-height: 400px;
}
.no-selection,
.no-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 350px;
  gap: var(--space-3);
  color: var(--c-text-3);
  font-size: 14px;
}

/* 报告查看器 */
.report-viewer-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: var(--space-5);
  border-bottom: 1px solid var(--c-bg-mute);
  background: var(--c-bg-soft);
}
.viewer-title-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.viewer-title-row h2 {
  font-size: 18px;
  font-weight: 600;
  color: var(--c-text-1);
  margin: 0;
}
.viewer-tags {
  display: flex;
  gap: var(--space-1);
}
.viewer-actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.viewer-date {
  font-size: 12px;
  color: var(--c-text-3);
}

/* 报告正文 */
.report-body {
  padding: var(--space-6);
  max-width: 800px;
  margin: 0 auto;
}
.report-section {
  margin-bottom: var(--space-6);
}
.report-section:last-child {
  margin-bottom: 0;
}
.section-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--c-text-1);
  margin: 0 0 var(--space-3) 0;
  padding-bottom: var(--space-2);
  border-bottom: 2px solid var(--c-brand);
  display: inline-block;
}
.section-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.section-para {
  font-size: 14px;
  color: var(--c-text-2);
  line-height: 1.8;
  margin: 0;
  white-space: pre-wrap;
}

/* 响应式 */
@media (max-width: 768px) {
  .report-main {
    grid-template-columns: 1fr;
  }
  .report-sidebar {
    max-height: 200px;
  }
  .input-row {
    flex-direction: column;
    align-items: stretch;
  }
  .report-viewer-header {
    flex-direction: column;
    gap: var(--space-3);
  }
}
</style>
