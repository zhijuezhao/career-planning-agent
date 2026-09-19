<script setup lang="ts">
/**
 * 业务区 - 我的简历（Task 14）
 * 数据源：GET /profile/snapshots（列表）→ GET /profile/snapshots/{id}（详情：five_layers/dimension_scores）
 * 展示：最新画像快照的五层画像 + 六维雷达 + 快照版本切换；「重新解析」跳引导区上传
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Document, Refresh, WarningFilled } from '@element-plus/icons-vue'
import PortraitFiveLayers from '@/components/PortraitFiveLayers.vue'
import SectionCard from '@/components/SectionCard.vue'
import EmptyState from '@/components/EmptyState.vue'
import RadarChart from '@/components/RadarChart.vue'
import { profileApi, type RadarOption, type SnapshotDetail, type SnapshotSummary } from '@/api/profile'
import { useJourneyStore } from '@/stores/journey'

const router = useRouter()
const journey = useJourneyStore()

const loading = ref(true)
const error = ref('')
const snapshots = ref<SnapshotSummary[]>([])
const selectedId = ref<number | null>(null)
const detail = ref<SnapshotDetail | null>(null)
const detailLoading = ref(false)
const radar = ref<RadarOption | null>(null)

const fiveLayers = computed<Record<string, any> | null>(() => detail.value?.five_layers ?? null)

/** 快照表单里若存过 resume_id，可用它取官方雷达数据 */
const resumeIdFromForm = computed<number | null>(() => {
  const raw = detail.value?.form?.resume_id
  const n = Number(raw)
  return Number.isFinite(n) && n > 0 ? n : null
})

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

/** 由冻结的六维分数拼装雷达（快照的 dimension_scores 已是扁平 {维度: 分数}） */
function radarFromScores(scores: Record<string, any> | null | undefined): RadarOption | null {
  if (!scores) return null
  const entries = Object.entries(scores).filter(([, v]) => typeof v === 'number')
  if (!entries.length) return null
  const values = entries.map(([, v]) => Number(v))
  const total = values.reduce((a, b) => a + b, 0)
  return {
    indicators: entries.map(([name]) => ({ name, max: 5 })),
    values,
    total_score: Math.round((total / values.length) * 100) / 100,
  }
}

async function loadRadar(): Promise<void> {
  radar.value = null
  const rid = resumeIdFromForm.value
  if (rid != null) {
    try {
      radar.value = await profileApi.getRadarData(rid)
      return
    } catch {
      /* 简历记录可能已被清理 → 回落到快照冻结分数 */
    }
  }
  radar.value = radarFromScores(detail.value?.dimension_scores)
}

async function loadDetail(id: number): Promise<void> {
  detailLoading.value = true
  try {
    detail.value = await profileApi.getSnapshotDetail(id)
    await loadRadar()
  } catch {
    detail.value = null
    radar.value = null
  } finally {
    detailLoading.value = false
  }
}

async function loadPage(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    snapshots.value = await profileApi.getSnapshots()
    const first = snapshots.value[0]
    if (first) {
      selectedId.value = first.id
      await loadDetail(first.id)
    } else {
      selectedId.value = null
      detail.value = null
      radar.value = null
    }
  } catch {
    error.value = '画像数据加载失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

onMounted(() => { void loadPage() })

async function selectSnapshot(id: number): Promise<void> {
  if (id === selectedId.value) return
  selectedId.value = id
  await loadDetail(id)
}

function goReparse(): void {
  journey.setGuideStep('resume')
  router.push('/guide/resume')
}
</script>

<template>
  <div class="resume-page">
    <header class="page-head">
      <div>
        <h2 class="page-title">我的简历</h2>
        <p class="page-desc">这里是你最新画像快照的五层能力画像与六维评分。</p>
      </div>
      <el-button type="primary" class="hover-lift press-effect" :icon="Document" @click="goReparse">
        重新解析
      </el-button>
    </header>

    <div v-if="loading" class="state-box">
      <el-icon class="is-loading" :size="24"><Refresh /></el-icon>
      <p class="state-text">正在加载画像…</p>
    </div>

    <p v-else-if="error" class="error-note">
      <el-icon><WarningFilled /></el-icon>
      <span>{{ error }}</span>
    </p>

    <EmptyState
      v-else-if="!snapshots.length"
      :icon="Document"
      title="还没有画像"
      description="上传一份 PDF 简历并完成解析，即可生成你的五层能力画像。"
      show-action
      action-text="去上传简历"
      @action="goReparse"
    />

    <template v-else>
      <SectionCard
        v-if="detail"
        title="六维能力雷达"
        :subtitle="`快照 ${shortSerial(detail.serial_no)} · ${formatDateTime(detail.created_at)}`"
      >
        <template #header>
          <span v-if="radar" class="dim-total">六维均值 {{ radar.total_score }}</span>
        </template>
        <RadarChart :data="radar" height="300px" />
      </SectionCard>

      <SectionCard title="五层能力画像" subtitle="来自当前快照冻结数据">
        <div v-if="detailLoading" class="detail-loading">正在读取快照详情…</div>
        <PortraitFiveLayers v-else :five-layers="fiveLayers" />
      </SectionCard>

      <SectionCard
        v-if="snapshots.length > 1"
        title="画像版本"
        :subtitle="`共 ${snapshots.length} 个快照`"
      >
        <ul class="snapshot-list">
          <li
            v-for="s in snapshots"
            :key="s.id"
            class="snapshot-item"
            :class="{ 'is-active': s.id === selectedId }"
            role="button"
            tabindex="0"
            @click="selectSnapshot(s.id)"
            @keydown.enter="selectSnapshot(s.id)"
          >
            <span class="snapshot-code">{{ shortSerial(s.serial_no) }}</span>
            <span class="snapshot-time">{{ formatDateTime(s.created_at) }}</span>
            <span v-if="s.id === selectedId" class="snapshot-flag">当前</span>
          </li>
        </ul>
      </SectionCard>
    </template>
  </div>
</template>

<style scoped>
.resume-page {
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
.dim-total {
  font-size: var(--text-sm);
  color: var(--c-text-2);
}
.detail-loading {
  font-size: var(--text-sm);
  color: var(--c-text-3);
}
.snapshot-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
}
.snapshot-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: var(--c-bg-soft);
  cursor: pointer;
  transition: border-color var(--duration-fast) ease, background var(--duration-fast) ease;
}
.snapshot-item:hover {
  background: var(--c-brand-lighter);
}
.snapshot-item.is-active {
  border-color: var(--c-brand);
}
.snapshot-code {
  font-size: var(--text-sm);
  color: var(--c-text-1);
}
.snapshot-time {
  flex: 1;
  font-size: var(--text-xs);
  color: var(--c-text-3);
}
.snapshot-flag {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--c-brand);
}
</style>
