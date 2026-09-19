<script setup lang="ts">
/**
 * 能力画像页面
 * 展示用户五层能力画像（意向/特质/实践/软技能/硬技能）+ 雷达图 + 维度评分
 * 调用的后端API：
 *   - GET /api/v1/resume/latest        获取最新简历状态
 *   - GET /api/v1/resume/{id}          获取简历详情（含五层画像数据）
 *   - GET /api/v1/resume/{id}/radar    获取雷达图数据
 * 调用的Agent：无（数据来自简历解析时生成）
 */
import { ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Aim,
  Star,
  Briefcase,
  MagicStick,
  Tools,
  Loading,
  Warning,
} from '@element-plus/icons-vue'
import * as echarts from 'echarts/core'
import { RadarChart } from 'echarts/charts'
import { CanvasRenderer } from 'echarts/renderers'
import { TooltipComponent } from 'echarts/components'
import { useResizeObserver } from '@vueuse/core'
import { profileApi, type ResumeDetailResponse, type RadarOption } from '../../api/profile'

echarts.use([RadarChart, CanvasRenderer, TooltipComponent])

// ==================== 状态 ====================

const loading = ref(false)
const resumeDetail = ref<ResumeDetailResponse | null>(null)
const radarData = ref<RadarOption | null>(null)
const activeLayer = ref<string>('intention')

const radarChartRef = ref<HTMLElement>()
let chartInstance: echarts.ECharts | null = null

// ==================== 五层配置 ====================

/** 五层键：与 fiveLayerData 的键保持一致，避免模板中 fiveLayerData[layer.key] 的隐式 any 索引（TS7053） */
type LayerKey = 'intention' | 'traits' | 'practice' | 'soft_skills' | 'hard_skills'

interface LayerConfigItem {
  key: LayerKey
  label: string
  icon: unknown
  color: string
  fields: string[]
}

const layerConfig: LayerConfigItem[] = [
  { key: 'intention', label: '意向层', icon: Aim, color: '#6366f1',
    fields: ['target_industry', 'target_position', 'expected_salary', 'expected_city'] },
  { key: 'traits', label: '特质层', icon: Star, color: '#f59e0b',
    fields: ['mbti', 'strengths', 'values'] },
  { key: 'practice', label: '实践层', icon: Briefcase, color: '#22c55e',
    fields: ['internships', 'projects', 'competitions', 'campus_activities'] },
  { key: 'soft_skills', label: '软技能层', icon: MagicStick, color: '#ec4899',
    fields: ['communication', 'stress_resilience', 'learning_ability', 'creativity', 'teamwork'] },
  { key: 'hard_skills', label: '硬技能层', icon: Tools, color: '#8b5cf6',
    fields: ['professional_skills', 'certificates', 'education', 'gpa'] },
]

// ==================== 计算属性 ====================

const fiveLayerData = computed(() => {
  const parsed = resumeDetail.value?.parsed_data
  if (!parsed) return {}
  return {
    intention: parsed.intention || parsed.ability_profile?.intention || {},
    traits: parsed.traits || parsed.ability_profile?.traits || {},
    practice: parsed.practice || parsed.ability_profile?.practice || {},
    soft_skills: parsed.soft_skills || parsed.ability_profile?.soft_skills || {},
    hard_skills: parsed.hard_skills || parsed.ability_profile?.hard_skills || {},
  }
})

const dimensionScores = computed(() => {
  const parsed = resumeDetail.value?.parsed_data
  if (!parsed) return []
  // 维度评分可能在不同位置
  return parsed.dimension_scores || parsed.dimension_scoring || parsed.scores || []
})

// ==================== 方法 ====================

async function loadProfile() {
  loading.value = true
  try {
    // 1. 获取最新简历
    const latest = await profileApi.getLatestResume()

    // 2. 获取简历详情
    const detail = await profileApi.getResumeDetail(latest.resume_id)
    resumeDetail.value = detail

    // 3. 如果已完成，获取雷达图数据
    if (detail.status === 'done') {
      try {
        const radar = await profileApi.getRadarData(latest.resume_id)
        radarData.value = radar
        renderRadar(radar)
      } catch {
        // 雷达图数据可选
      }
    }
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || '加载画像数据失败')
  } finally {
    loading.value = false
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
      splitNumber: 4,
      axisName: { color: '#475569', fontSize: 12 },
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
        symbolSize: 6,
      }],
    }],
    tooltip: { trigger: 'item' },
  })
}

function getFieldValue(data: Record<string, any>, field: string): string {
  const val = data[field]
  if (val === undefined || val === null || val === '') return '—'
  if (Array.isArray(val)) return val.join('、')
  if (typeof val === 'object') return JSON.stringify(val)
  return String(val)
}

function getScoreColor(score: number): string {
  if (score >= 4.0) return '#22c55e'
  if (score >= 3.0) return '#6366f1'
  if (score >= 2.0) return '#f59e0b'
  return '#ef4444'
}

// ==================== 生命周期 ====================

onMounted(() => {
  loadProfile()
  if (radarChartRef.value) {
    useResizeObserver(radarChartRef.value, () => chartInstance?.resize())
  }
})
</script>

<template>
  <div class="profile-page">
    <!-- 加载状态 -->
    <div v-if="loading" class="loading-container">
      <el-icon :size="32" class="is-loading" color="var(--c-brand)"><Loading /></el-icon>
      <p>正在加载画像数据...</p>
    </div>

    <!-- 空状态：无简历 -->
    <div v-else-if="!resumeDetail" class="empty-state">
      <el-icon :size="48" color="var(--c-text-3)"><Warning /></el-icon>
      <h3>暂无画像数据</h3>
      <p>请先上传简历，系统将自动分析生成你的能力画像</p>
      <el-button type="primary" @click="$router.push('/resume')">前往上传简历</el-button>
    </div>

    <!-- 处理中状态 -->
    <div v-else-if="resumeDetail.status !== 'done'" class="processing-state">
      <el-icon :size="32" class="is-loading" color="var(--c-brand)"><Loading /></el-icon>
      <h3>简历正在处理中</h3>
      <p>当前状态：{{ resumeDetail.status }}，请稍后再来查看</p>
    </div>

    <!-- 画像内容 -->
    <div v-else class="profile-content">
      <!-- 顶部概览 -->
      <div class="profile-header">
        <div class="header-info">
          <h2>能力画像</h2>
          <span class="version-tag">v{{ resumeDetail.parsed_data?.ability_profile?.version || 1 }}</span>
          <span class="update-time">更新于 {{ new Date(resumeDetail.updated_at).toLocaleDateString('zh-CN') }}</span>
        </div>
      </div>

      <!-- 雷达图 + 维度评分 -->
      <div class="overview-grid">
        <!-- 雷达图 -->
        <div class="widget radar-widget">
          <div class="widget-header">
            <span class="widget-title">能力雷达图</span>
            <span v-if="radarData" class="total-score">
              综合 {{ radarData.total_score?.toFixed(1) || '—' }} / 5
            </span>
          </div>
          <div v-if="radarData" ref="radarChartRef" class="radar-chart"></div>
          <div v-else class="no-radar">暂无雷达图数据</div>
        </div>

        <!-- 维度评分 -->
        <div class="widget scores-widget">
          <div class="widget-header">
            <span class="widget-title">维度评分</span>
          </div>
          <div v-if="dimensionScores.length > 0" class="dimension-list">
            <div
              v-for="(item, idx) in dimensionScores"
              :key="idx"
              class="dimension-item"
            >
              <div class="dimension-name">{{ item.top_dimension || item.dimension || '—' }}</div>
              <div class="dimension-bar-bg">
                <div
                  class="dimension-bar-fill"
                  :style="{
                    width: `${((item.score || 0) / 5) * 100}%`,
                    backgroundColor: getScoreColor(item.score || 0)
                  }"
                ></div>
              </div>
              <div class="dimension-score" :style="{ color: getScoreColor(item.score || 0) }">
                {{ (item.score || 0).toFixed(1) }}
              </div>
            </div>
          </div>
          <div v-else class="no-scores">暂无维度评分数据</div>
        </div>
      </div>

      <!-- 五层画像 Tab -->
      <div class="widget layers-widget">
        <div class="widget-header">
          <span class="widget-title">五层能力画像</span>
        </div>
        <div class="layers-tabs">
          <button
            v-for="layer in layerConfig"
            :key="layer.key"
            class="layer-tab"
            :class="{ active: activeLayer === layer.key }"
            @click="activeLayer = layer.key"
          >
            <el-icon :size="16"><component :is="layer.icon" /></el-icon>
            {{ layer.label }}
          </button>
        </div>
        <div class="layer-content">
          <div
            v-for="layer in layerConfig"
            :key="layer.key"
            v-show="activeLayer === layer.key"
            class="layer-panel"
          >
            <div class="field-grid">
              <div
                v-for="field in layer.fields"
                :key="field"
                class="field-item"
              >
                <div class="field-label">{{ field }}</div>
                <div class="field-value">{{ getFieldValue(fiveLayerData[layer.key] || {}, field) }}</div>
              </div>
            </div>
            <div v-if="Object.keys(fiveLayerData[layer.key] || {}).length === 0" class="no-data">
              暂无{{ layer.label }}数据
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.profile-page {
  max-width: 1100px;
  margin: 0 auto;
}

/* 加载 & 空状态 */
.loading-container,
.empty-state,
.processing-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 50vh;
  text-align: center;
  gap: var(--space-4);
}
.loading-container p,
.empty-state p,
.processing-state p {
  font-size: 14px;
  color: var(--c-text-3);
}
.empty-state h3,
.processing-state h3 {
  font-size: 18px;
  font-weight: 600;
  color: var(--c-text-1);
  margin: 0;
}

/* 头部 */
.profile-header {
  margin-bottom: var(--space-5);
}
.header-info {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.header-info h2 {
  font-size: 20px;
  font-weight: 600;
  color: var(--c-text-1);
  margin: 0;
}
.version-tag {
  padding: 2px 8px;
  border-radius: var(--radius-full);
  background: var(--c-brand-lighter);
  color: var(--c-brand);
  font-size: 12px;
  font-weight: 500;
}
.update-time {
  font-size: 13px;
  color: var(--c-text-3);
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
.widget-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--c-text-1);
}

/* 雷达图 + 维度评分 Grid */
.overview-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-5);
  margin-bottom: var(--space-5);
}
.total-score {
  font-size: 14px;
  font-weight: 600;
  color: var(--c-brand);
}
.radar-chart {
  height: 280px;
  width: 100%;
}
.no-radar,
.no-scores,
.no-data {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100px;
  color: var(--c-text-3);
  font-size: 13px;
}

/* 维度评分 */
.dimension-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.dimension-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.dimension-name {
  width: 100px;
  font-size: 13px;
  color: var(--c-text-2);
  flex-shrink: 0;
}
.dimension-bar-bg {
  flex: 1;
  height: 8px;
  background: var(--c-bg-soft);
  border-radius: var(--radius-full);
  overflow: hidden;
}
.dimension-bar-fill {
  height: 100%;
  border-radius: var(--radius-full);
  transition: width 0.6s ease;
}
.dimension-score {
  width: 32px;
  font-size: 13px;
  font-weight: 600;
  text-align: right;
  flex-shrink: 0;
}

/* 五层画像 */
.layers-tabs {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
  border-bottom: 1px solid var(--c-bg-mute);
  padding-bottom: var(--space-3);
}
.layer-tab {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 14px;
  border-radius: var(--radius-full);
  border: 1px solid var(--c-bg-mute);
  background: var(--c-surface);
  color: var(--c-text-2);
  font-size: 13px;
  cursor: pointer;
  transition: all var(--duration-fast) ease;
}
.layer-tab:hover {
  border-color: var(--c-brand);
  color: var(--c-brand);
}
.layer-tab.active {
  background: var(--c-brand-lighter);
  border-color: var(--c-brand);
  color: var(--c-brand);
  font-weight: 500;
}

/* 五层内容 */
.layer-content {
  min-height: 150px;
}
.field-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-4);
}
.field-item {
  padding: var(--space-3) var(--space-4);
  background: var(--c-bg-soft);
  border-radius: var(--radius-sm);
}
.field-label {
  font-size: 12px;
  color: var(--c-text-3);
  margin-bottom: var(--space-1);
  text-transform: capitalize;
}
.field-value {
  font-size: 14px;
  color: var(--c-text-1);
  font-weight: 500;
  word-break: break-all;
}

/* 响应式 */
@media (max-width: 768px) {
  .overview-grid {
    grid-template-columns: 1fr;
  }
  .field-grid {
    grid-template-columns: 1fr;
  }
  .dimension-name {
    width: 70px;
  }
}
</style>
