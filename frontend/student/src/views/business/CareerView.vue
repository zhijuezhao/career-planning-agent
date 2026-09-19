<script setup lang="ts">
/**
 * 业务区 - 职业报告（Task 15）
 * 数据源：GET /reports/records（列表）、GET /reports/records/{id}（全文）、
 *        GET /reports/records/{id}/download（惰性生成 Word，blob 下载）
 * 结构：左列版本卡列表 → 右列 ReportMarkdown 全文 + 下载按钮；无报告时空态去生成。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Download, Notebook, Refresh, WarningFilled } from '@element-plus/icons-vue'
import ReportMarkdown from '@/components/ReportMarkdown.vue'
import SectionCard from '@/components/SectionCard.vue'
import EmptyState from '@/components/EmptyState.vue'
import { reportApi, type ReportRecord, type ReportRecordDetail } from '@/api/report'
import { useJourneyStore } from '@/stores/journey'

const router = useRouter()
const journey = useJourneyStore()

const loading = ref(true)
const error = ref('')
const records = ref<ReportRecord[]>([])
const selectedId = ref<number | null>(null)
const detail = ref<ReportRecordDetail | null>(null)
const detailLoading = ref(false)
const downloading = ref(false)

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function shortSerial(serial: string | null | undefined): string {
  return serial ? String(serial).slice(0, 8) : '—'
}

const selectedRecord = computed<ReportRecord | null>(
  () => records.value.find(r => r.id === selectedId.value) ?? null)

async function loadDetail(id: number): Promise<void> {
  detailLoading.value = true
  try {
    detail.value = await reportApi.getRecord(id)
  } catch {
    detail.value = null
    ElMessage.error('报告详情加载失败')
  } finally {
    detailLoading.value = false
  }
}

async function loadPage(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    records.value = await reportApi.getRecords()
    // 徽标/版本数刷新失败不影响正文
    try {
      await journey.fetchStatus()
    } catch {
      /* 离线等场景忽略 */
    }
    const first = records.value[0]
    if (first) {
      selectedId.value = first.id
      await loadDetail(first.id)
    } else {
      selectedId.value = null
      detail.value = null
    }
  } catch {
    error.value = '报告列表加载失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

onMounted(() => { void loadPage() })

async function selectRecord(id: number): Promise<void> {
  if (id === selectedId.value) return
  selectedId.value = id
  await loadDetail(id)
}

async function downloadWord(): Promise<void> {
  const rec = selectedRecord.value
  if (!rec || downloading.value) return
  downloading.value = true
  try {
    const blob = await reportApi.downloadWord(rec.id)
    const url = URL.createObjectURL(blob as Blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `生涯发展报告_v${rec.version}_${shortSerial(rec.serial_no)}.docx`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    ElMessage.success('Word 已开始下载')
    await loadDetail(rec.id)   // 惰性生成后后端回填 word_file_path
  } catch {
    ElMessage.error('下载失败，请稍后重试')
  } finally {
    downloading.value = false
  }
}

function goGenerate(): void {
  journey.setGuideStep('done')
  router.push('/guide/done')
}
</script>

<template>
  <div class="career-page">
    <header class="page-head">
      <div>
        <h2 class="page-title">职业报告</h2>
        <p class="page-desc">共 {{ records.length }} 份报告；选择版本查看全文或下载 Word。</p>
      </div>
      <el-button
        v-if="records.length"
        type="primary"
        class="hover-lift press-effect"
        :icon="Download"
        :loading="downloading"
        @click="downloadWord"
      >
        下载 Word
      </el-button>
    </header>

    <div v-if="loading" class="state-box">
      <el-icon class="is-loading" :size="24"><Refresh /></el-icon>
      <p class="state-text">正在加载报告…</p>
    </div>

    <p v-else-if="error" class="error-note">
      <el-icon><WarningFilled /></el-icon>
      <span>{{ error }}</span>
    </p>

    <EmptyState
      v-else-if="!records.length"
      :icon="Notebook"
      title="还没有报告"
      description="完成选岗与策略确认后即可生成你的第一份职业规划报告。"
      show-action
      action-text="去生成报告"
      @action="goGenerate"
    />

    <div v-else class="career-body">
      <aside class="version-list">
        <button
          v-for="r in records"
          :key="r.id"
          class="version-card"
          :class="{ 'is-active': r.id === selectedId }"
          @click="selectRecord(r.id)"
        >
          <span class="version-head">
            <span class="version-no">第 {{ r.version }} 版</span>
            <span class="version-code">{{ shortSerial(r.serial_no) }}</span>
          </span>
          <span class="version-desc">{{ r.description || '—' }}</span>
          <span class="version-time">{{ formatDateTime(r.created_at) }}</span>
        </button>
      </aside>

      <div class="report-main">
        <SectionCard
          :title="selectedRecord ? `第 ${selectedRecord.version} 版全文` : '报告全文'"
          :subtitle="selectedRecord ? formatDateTime(selectedRecord.created_at) : ''"
        >
          <template #header>
            <el-button link type="primary" :loading="downloading" @click="downloadWord">
              下载 Word
            </el-button>
          </template>
          <div v-if="detailLoading" class="detail-loading">正在读取报告全文…</div>
          <ReportMarkdown v-else :text="detail?.report_text" />
        </SectionCard>
      </div>
    </div>
  </div>
</template>

<style scoped>
.career-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
}
.page-title {
  margin: 0 0 var(--space-2);
  font-family: var(--font-display);
  font-size: 28px;
  font-weight: 600;
  color: var(--c-text-1);
}
.page-desc {
  margin: 0;
  font-size: var(--text-base);
  color: var(--c-text-2);
}
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
.career-body {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: var(--space-5);
  align-items: start;
}
.version-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.version-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  width: 100%;
  padding: var(--space-3) var(--space-4);
  text-align: left;
  background: var(--c-surface);
  border: 1px solid var(--c-bg-mute);
  border-radius: var(--radius-md);
  cursor: pointer;
  font-family: inherit;
  transition: border-color var(--duration-fast) ease, box-shadow var(--duration-fast) ease;
}
.version-card:hover {
  box-shadow: var(--shadow-sm);
}
.version-card.is-active {
  border-color: var(--c-brand);
  background: var(--c-brand-lighter);
}
.version-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}
.version-no {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--c-text-1);
}
.version-code {
  font-size: var(--text-xs);
  color: var(--c-text-3);
}
.version-desc {
  font-size: var(--text-xs);
  color: var(--c-text-2);
}
.version-time {
  font-size: var(--text-xs);
  color: var(--c-text-3);
}
.report-main {
  min-width: 0;
}
.detail-loading {
  font-size: var(--text-sm);
  color: var(--c-text-3);
}

@media (max-width: 1024px) {
  .career-body {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
