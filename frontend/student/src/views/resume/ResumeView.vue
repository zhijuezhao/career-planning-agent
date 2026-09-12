<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { UploadFilled, Document, CircleCheck, Loading } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts/core'
import { RadarChart } from 'echarts/charts'
import { CanvasRenderer } from 'echarts/renderers'
import { TooltipComponent } from 'echarts/components'
import { useResizeObserver } from '@vueuse/core'
import { resumeApi } from '../../api/resume'
import type { ResumeDetail, ReportData, RadarOption } from '../../api/resume'

echarts.use([RadarChart, CanvasRenderer, TooltipComponent])

const uploading = ref(false)
const polling = ref(false)
const currentResumeId = ref<number | null>(null)
const detail = ref<ResumeDetail | null>(null)
const report = ref<ReportData | null>(null)
const radarOption = ref<RadarOption | null>(null)
const statusText = ref('')
let pollTimer: ReturnType<typeof setInterval> | null = null

const radarChartRef = ref<HTMLElement>()
let chartInstance: echarts.ECharts | null = null

const STATUS_LABELS: Record<string, string> = {
  uploaded: '已上传，等待处理',
  parsing: '正在解析简历...',
  parsed: '解析完成，正在评分...',
  scoring: '正在写入维度评分...',
  embedding: '正在生成向量...',
  reporting: '正在生成报告...',
  done: '分析完成',
  failed: '处理失败',
}

async function handleUpload(uploadFile: { file: File }) {
  uploading.value = true
  statusText.value = '上传中...'
  try {
    const res = await resumeApi.upload(uploadFile.file)
    currentResumeId.value = res.resume_id
    startPolling(res.resume_id)
  } catch {
    uploading.value = false
    statusText.value = ''
  }
}

function startPolling(resumeId: number) {
  polling.value = true
  pollTimer = setInterval(async () => {
    try {
      const d = await resumeApi.getDetail(resumeId)
      statusText.value = STATUS_LABELS[d.status] || d.status
      if (d.status === 'done') {
        stopPolling()
        detail.value = d
        await loadResults(resumeId)
      } else if (d.status === 'failed') {
        stopPolling()
        ElMessage.error(d.error_message || '简历处理失败')
      }
    } catch {
      stopPolling()
    }
  }, 2000)
}

function stopPolling() {
  polling.value = false
  uploading.value = false
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function loadResults(resumeId: number) {
  try {
    const [reportRes, radarRes] = await Promise.allSettled([
      resumeApi.getReport(resumeId),
      resumeApi.getRadar(resumeId),
    ])
    if (reportRes.status === 'fulfilled') report.value = reportRes.value
    if (radarRes.status === 'fulfilled') {
      radarOption.value = radarRes.value
      renderRadar(radarRes.value)
    }
  } catch {
    // results are optional
  }
}

function renderRadar(option: RadarOption) {
  if (!radarChartRef.value) return
  if (!chartInstance) {
    chartInstance = echarts.init(radarChartRef.value)
  }
  chartInstance.setOption({
    radar: {
      indicator: option.indicators,
      shape: 'polygon',
      splitNumber: 5,
      axisName: { color: '#475569', fontSize: 11 },
      splitLine: { lineStyle: { color: '#e2e8f0' } },
      splitArea: { show: false },
      axisLine: { lineStyle: { color: '#e2e8f0' } },
    },
    series: [{
      type: 'radar',
      data: [{
        value: option.values,
        areaStyle: { color: 'rgba(99, 102, 241, 0.15)' },
        lineStyle: { color: '#6366f1', width: 2 },
        itemStyle: { color: '#6366f1' },
        symbol: 'circle',
        symbolSize: 5,
      }],
    }],
    tooltip: { trigger: 'item' },
  })
}

onMounted(async () => {
  try {
    const latest = await resumeApi.getLatest()
    currentResumeId.value = latest.resume_id
    if (latest.status === 'done') {
      const d = await resumeApi.getDetail(latest.resume_id)
      detail.value = d
      await loadResults(latest.resume_id)
    } else if (latest.status !== 'failed') {
      statusText.value = STATUS_LABELS[latest.status] || latest.status
      startPolling(latest.resume_id)
    }
  } catch {
    // no resume yet
  }
  if (radarChartRef.value) {
    useResizeObserver(radarChartRef.value, () => chartInstance?.resize())
  }
})

onUnmounted(() => stopPolling())
</script>

<template>
  <div class="resume-page">
    <!-- Upload Section -->
    <div class="upload-section" v-if="!detail && !polling">
      <el-upload
        drag
        :auto-upload="false"
        :show-file-list="false"
        accept=".pdf"
        :on-change="handleUpload"
        class="upload-dragger"
      >
        <el-icon :size="48" color="var(--c-brand-light)"><UploadFilled /></el-icon>
        <div class="upload-text">拖拽 PDF 简历到此处，或点击上传</div>
        <div class="upload-hint">仅支持 PDF 格式，最大 10MB</div>
      </el-upload>
    </div>

    <!-- Processing Status -->
    <div class="status-bar" v-if="polling || uploading">
      <el-icon class="is-loading"><Loading /></el-icon>
      <span>{{ statusText }}</span>
    </div>

    <!-- Results Panel -->
    <div class="results" v-if="detail">
      <div class="results-header">
        <div class="file-info">
          <el-icon><Document /></el-icon>
          <span>{{ detail.file_name }}</span>
          <el-tag type="success" effect="plain" size="small">
            <el-icon><CircleCheck /></el-icon> 分析完成
          </el-tag>
        </div>
      </div>

      <div class="results-grid">
        <!-- Radar Chart -->
        <div class="result-card" v-if="radarOption">
          <h3>能力雷达图</h3>
          <div class="score-badge">综合 {{ radarOption.total_score.toFixed(1) }} / 5</div>
          <div ref="radarChartRef" class="radar-chart"></div>
        </div>

        <!-- Report -->
        <div class="result-card report-card" v-if="report">
          <h3>职业能力分析报告</h3>
          <div class="report-content" v-if="report.report_content">
            {{ report.report_content.text || JSON.stringify(report.report_content) }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.resume-page {
  max-width: 960px;
  margin: 0 auto;
}

.upload-section {
  display: flex;
  justify-content: center;
  padding: var(--space-8) 0;
}
.upload-dragger :deep(.el-upload-dragger) {
  padding: var(--space-8);
  border-radius: var(--radius-lg);
  border: 2px dashed var(--c-bg-mute);
  transition: border-color var(--duration-fast) ease;
}
.upload-dragger :deep(.el-upload-dragger:hover) {
  border-color: var(--c-brand);
}
.upload-text {
  margin-top: var(--space-4);
  font-size: 16px;
  color: var(--c-text-1);
  font-weight: 500;
}
.upload-hint {
  margin-top: var(--space-2);
  font-size: 13px;
  color: var(--c-text-3);
}

.status-bar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  background: var(--c-brand-lighter);
  border-radius: var(--radius-md);
  color: var(--c-brand);
  font-size: 14px;
  font-weight: 500;
  margin-bottom: var(--space-5);
}

.results-header {
  margin-bottom: var(--space-5);
}
.file-info {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  font-size: 15px;
  color: var(--c-text-1);
  font-weight: 500;
}
.file-info .el-tag {
  margin-left: var(--space-2);
}

.results-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-5);
}
.result-card {
  background: var(--c-surface);
  border: 1px solid var(--c-bg-mute);
  border-radius: var(--radius-md);
  padding: var(--space-5);
  box-shadow: var(--shadow-xs);
}
.result-card h3 {
  font-size: 15px;
  font-weight: 600;
  color: var(--c-text-1);
  margin-bottom: var(--space-4);
}

.score-badge {
  text-align: center;
  font-size: 14px;
  font-weight: 600;
  color: var(--c-brand);
  margin-bottom: var(--space-3);
}
.radar-chart {
  height: 280px;
  width: 100%;
}

.report-card {
  grid-column: span 2;
}
.report-content {
  font-size: 14px;
  line-height: 1.8;
  color: var(--c-text-2);
  white-space: pre-wrap;
  max-height: 500px;
  overflow-y: auto;
}

@media (max-width: 768px) {
  .results-grid {
    grid-template-columns: 1fr;
  }
  .report-card {
    grid-column: span 1;
  }
}
</style>
