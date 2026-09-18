<script setup lang="ts">
/**
 * 引导第 2 步：画像解析结果确认
 * 展示 AI 解析出的五层能力画像 + 六维雷达图，并「确认回填」持久化画像 + 生成快照
 * 数据来源优先级：sessionStorage('guide.parse_result') → GET /resume/latest + /resume/{id}
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh, Search } from '@element-plus/icons-vue'
import RadarChart from '@/components/RadarChart.vue'
import EmptyState from '@/components/EmptyState.vue'
import { profileApi, type AbilityProfileData, type DimensionScoring, type RadarOption } from '@/api/profile'
import { useJourneyStore } from '@/stores/journey'

interface LayerMeta {
  key: keyof AbilityProfileData
  label: string
  hint: string
}

interface LayerItem {
  key: string
  text: string
}

interface LayerCard {
  key: string
  label: string
  hint: string
  items: LayerItem[]
}

const PARSE_RESULT_KEY = 'guide.parse_result'
const LAYER_META: LayerMeta[] = [
  { key: 'intention', label: '意向层', hint: '目标行业 / 岗位 / 城市 / 薪资' },
  { key: 'traits', label: '特质层', hint: '性格标签 / 擅长方向 / 价值观' },
  { key: 'practice', label: '实践层', hint: '实习 / 项目 / 竞赛 / 校园经历' },
  { key: 'soft_skills', label: '软技能层', hint: '沟通 / 协作 / 抗压 / 学习' },
  { key: 'hard_skills', label: '硬技能层', hint: '专业技能 / 学历 / 证书' },
]

const router = useRouter()
const journey = useJourneyStore()

const loading = ref(true)
const confirming = ref(false)
const isEmpty = ref(false)
const fiveLayers = ref<AbilityProfileData | null>(null)
const scoring = ref<DimensionScoring | null>(null)
const radar = ref<RadarOption | null>(null)
const resumeId = ref<number | null>(null)

/* ---------------- 防御性格式化（五层内容 shape 不可知） ---------------- */

function formatScalar(value: unknown): string {
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return ''
}

function formatValue(value: unknown): string {
  if (value == null) return ''
  const scalar = formatScalar(value)
  if (scalar) return scalar
  if (Array.isArray(value)) {
    return value.map(item => formatValue(item)).filter(Boolean).join('、')
  }
  if (typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => {
        const text = formatValue(item)
        return text ? `${key}：${text}` : ''
      })
      .filter(Boolean)
      .join('；')
  }
  return ''
}

function toItems(value: unknown): LayerItem[] {
  if (value == null || typeof value !== 'object' || Array.isArray(value)) {
    const text = formatValue(value)
    return text ? [{ key: '', text }] : []
  }
  return Object.entries(value as Record<string, unknown>)
    .map(([key, item]) => ({ key, text: formatValue(item) }))
    .filter(item => item.text !== '')
}

const layerCards = computed<LayerCard[]>(() =>
  LAYER_META.map((meta) => {
    const source = fiveLayers.value ? fiveLayers.value[meta.key] : null
    return { key: meta.key, label: meta.label, hint: meta.hint, items: toItems(source) }
  }))

const hasPortrait = computed(() => {
  if (!fiveLayers.value) return false
  return layerCards.value.some(layer => layer.items.length > 0)
})

/** 后端未返回雷达数据时，用六维评分自行拼装 */
const radarFromScoring = computed<RadarOption | null>(() => {
  const dims = scoring.value?.dimensions
  if (!dims) return null
  const names = Object.keys(dims)
  if (names.length === 0) return null
  return {
    indicators: names.map(name => ({ name, max: 5 })),
    values: names.map(name => Number(dims[name]?.score ?? 0)),
    total_score: Number(scoring.value?.total_dim_score ?? 0),
  }
})

const radarData = computed<RadarOption | null>(() => radar.value ?? radarFromScoring.value)

const dimensionRows = computed(() => {
  const dims = scoring.value?.dimensions
  if (!dims) return []
  return Object.entries(dims).map(([name, dim]) => ({
    name,
    score: Number(dim?.score ?? 0),
  }))
})

/* ---------------- 加载 ---------------- */

interface SessionPayload {
  resume_id?: number
  five_layers?: AbilityProfileData | null
  dimension_scoring?: DimensionScoring | null
}

function readSessionResult(): SessionPayload | null {
  try {
    const raw = sessionStorage.getItem(PARSE_RESULT_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as SessionPayload | null
    if (!parsed || typeof parsed !== 'object') return null
    if (!parsed.five_layers && !parsed.dimension_scoring) return null
    return parsed
  } catch {
    return null   // 解析失败 → 回退到接口
  }
}

/** parsed_data 可能是 { five_layers, dimension_scoring } 包裹态，也可能是五层平铺态 */
function extractFromParsedData(parsedData: Record<string, any> | null | undefined): {
  layers: AbilityProfileData | null
  dims: DimensionScoring | null
} {
  if (!parsedData || typeof parsedData !== 'object') return { layers: null, dims: null }
  const wrapped = parsedData.five_layers
  const dims = (parsedData.dimension_scoring ?? null) as DimensionScoring | null
  if (wrapped && typeof wrapped === 'object') {
    return { layers: wrapped as AbilityProfileData, dims }
  }
  const flat: AbilityProfileData = {
    intention: parsedData.intention,
    traits: parsedData.traits,
    practice: parsedData.practice,
    soft_skills: parsedData.soft_skills,
    hard_skills: parsedData.hard_skills,
  }
  const hasAny = LAYER_META.some(meta => flat[meta.key])
  return { layers: hasAny ? flat : null, dims }
}

async function loadRadar(): Promise<void> {
  const id = resumeId.value
  if (id == null) return
  try {
    radar.value = await profileApi.getRadarData(id)
  } catch {
    radar.value = null   // 交给 radarFromScoring 兜底
  }
}

async function loadFromSession(): Promise<boolean> {
  const payload = readSessionResult()
  if (!payload) return false
  fiveLayers.value = (payload.five_layers ?? null) as AbilityProfileData | null
  scoring.value = (payload.dimension_scoring ?? null) as DimensionScoring | null
  resumeId.value = typeof payload.resume_id === 'number' ? payload.resume_id : null
  if (!fiveLayers.value && !scoring.value) return false
  await loadRadar()
  return true
}

async function loadFromApi(): Promise<void> {
  try {
    const latest = await profileApi.getLatestResume()
    resumeId.value = latest.resume_id
    const detail = await profileApi.getResumeDetail(latest.resume_id)
    const extracted = extractFromParsedData(detail.parsed_data)
    fiveLayers.value = extracted.layers
    scoring.value = extracted.dims
    await loadRadar()
    if (!fiveLayers.value && !scoring.value) isEmpty.value = true
  } catch {
    isEmpty.value = true   // 无简历（404）或接口异常 → 空状态，绝不抛出
  }
}

async function bootstrap(): Promise<void> {
  loading.value = true
  isEmpty.value = false
  try {
    const fromSession = await loadFromSession()
    if (!fromSession) await loadFromApi()
  } catch {
    isEmpty.value = true
  } finally {
    loading.value = false
  }
}

onMounted(() => { void bootstrap() })

/* ---------------- 确认回填并生成快照 ---------------- */

function clearParseResult(): void {
  try {
    sessionStorage.removeItem(PARSE_RESULT_KEY)
  } catch {
    /* sessionStorage 不可用时忽略 */
  }
}

function errorMessage(err: unknown): string {
  const e = err as { response?: { data?: { detail?: unknown } } } | null
  const detail = e?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  return '画像生成失败'
}

async function confirmAndSnapshot(): Promise<void> {
  if (!hasPortrait.value || confirming.value) return
  confirming.value = true
  try {
    const layers = fiveLayers.value ?? {}
    const scoringValue = scoring.value
    // 六维分数需要 **扁平** {维度名: 分数} 映射：后端 _candidate_scores() 直接读
    // snapshot.six_dim_scores_json 的 key 作为维度名做逐维对比（R-11.7）。
    // 若把整份 DimensionScoring 塞进去，聚合循环会把 total_dim_score/profile_type/
    // dimensions 当成维度名，导致六维对比全部错位。
    const sixDimFlat: Record<string, number> = {}
    for (const [dimName, detail] of Object.entries(scoringValue?.dimensions ?? {})) {
      sixDimFlat[dimName] = Number(detail?.score ?? 0)
    }
    // 顶层平铺 + five_layers 双写：后端按顶层 intention/practice/hard_skills 推导当前步骤
    const resumeForm = {
      ...layers,
      five_layers: layers,
      // 供快照冻结用的完整评分对象
      dimension_scoring: scoringValue ?? {},
      // 扁平六维（匹配服务读这个字段）
      six_dim_scores: sixDimFlat,
    }
    await profileApi.updateProfile(resumeForm as Record<string, any>)
    const task = await profileApi.createSnapshot()
    const res = await profileApi.pollSnapshot(task.task_id, 20)
    if (res.ok) {
      journey.setGuideStep('match')
      // 与服务端对齐（后端 derive_zone 对「有快照无报告」返回 guide_step=match）；
      // 失败不阻塞跳转，本地 setGuideStep 已足够解锁「下一步」
      try {
        await journey.fetchStatus()
      } catch {
        /* 离线等场景忽略 */
      }
      clearParseResult()
      ElMessage.success('画像已生成')
      router.push('/guide/match')
    } else {
      ElMessage.error(res.message || '画像生成失败')
    }
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    confirming.value = false
  }
}
</script>

<template>
  <div class="guide-page">
    <header class="page-head">
      <h2 class="guide-title">画像解析</h2>
      <p class="guide-desc">AI 已从你的简历中解析出五层能力画像，确认无误后回填并生成画像快照。</p>
    </header>

    <div v-if="loading" class="state-box">
      <el-icon class="is-loading" :size="24"><Refresh /></el-icon>
      <p class="state-text">正在加载解析结果…</p>
    </div>

    <EmptyState
      v-else-if="isEmpty && !hasPortrait"
      :icon="Search"
      title="还没有解析结果"
      description="先上传简历完成解析，再回到这一步确认画像。"
      show-action
      action-text="去上传简历"
      @action="router.push('/guide/resume')"
    />

    <template v-else>
      <div class="radar-panel">
        <div class="radar-head">
          <span class="panel-title">六维能力雷达</span>
          <span v-if="scoring" class="dim-total">
            综合评分 <strong>{{ scoring.total_dim_score }}</strong>
          </span>
        </div>
        <RadarChart :data="radarData" height="280px" />
        <ul v-if="dimensionRows.length" class="dim-list">
          <li v-for="row in dimensionRows" :key="row.name" class="dim-row">
            <span class="dim-name">{{ row.name }}</span>
            <span class="dim-value">{{ row.score }}</span>
          </li>
        </ul>
      </div>

      <div class="layer-list">
        <section v-for="layer in layerCards" :key="layer.key" class="layer-card">
          <div class="layer-head">
            <h3 class="layer-title">{{ layer.label }}</h3>
            <span class="layer-hint">{{ layer.hint }}</span>
          </div>
          <div v-if="layer.items.length" class="layer-body">
            <p v-for="item in layer.items" :key="item.key" class="layer-item">
              <span v-if="item.key" class="item-key">{{ item.key }}</span>
              <span class="item-text">{{ item.text }}</span>
            </p>
          </div>
          <p v-else class="layer-empty">暂无</p>
        </section>
      </div>

      <div class="confirm-bar">
        <el-button
          type="primary"
          class="confirm-btn"
          :loading="confirming"
          :disabled="!hasPortrait"
          @click="confirmAndSnapshot"
        >
          确认回填并生成画像
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

/* 雷达面板 */
.radar-panel {
  background: var(--c-surface);
  border: 1px solid var(--c-bg-mute);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  padding: var(--space-5);
}
.radar-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-2);
}
.panel-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--c-text-1);
}
.dim-total {
  font-size: var(--text-sm);
  color: var(--c-text-2);
}
.dim-total strong {
  font-family: var(--font-display);
  font-size: var(--text-base);
  color: var(--c-brand);
  margin-left: var(--space-1);
}
.dim-list {
  list-style: none;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2) var(--space-4);
  margin: var(--space-3) 0 0;
  padding: var(--space-3) 0 0;
  border-top: 1px solid var(--c-bg-mute);
}
.dim-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-xs);
  color: var(--c-text-3);
}
.dim-name {
  color: var(--c-text-2);
}
.dim-value {
  font-weight: 600;
  color: var(--c-text-1);
}

/* 五层卡片 */
.layer-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.layer-card {
  background: var(--c-surface);
  border: 1px solid var(--c-bg-mute);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-xs);
  padding: var(--space-5);
  transition: box-shadow 0.2s ease;
}
.layer-card:hover {
  box-shadow: var(--shadow-md);
}
.layer-head {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}
.layer-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--c-text-1);
  margin: 0;
}
.layer-hint {
  font-size: var(--text-xs);
  color: var(--c-text-3);
}
.layer-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.layer-item {
  display: flex;
  gap: var(--space-2);
  margin: 0;
  font-size: var(--text-sm);
  line-height: 1.6;
}
.item-key {
  flex-shrink: 0;
  min-width: 84px;
  color: var(--c-text-3);
}
.item-text {
  color: var(--c-text-1);
  word-break: break-word;
}
.layer-empty {
  margin: 0;
  font-size: var(--text-sm);
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
  .item-key {
    min-width: 64px;
  }
}
</style>
