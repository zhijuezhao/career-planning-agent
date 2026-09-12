<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useTransition, useResizeObserver } from '@vueuse/core'
import * as echarts from 'echarts/core'
import { RadarChart } from 'echarts/charts'
import { CanvasRenderer } from 'echarts/renderers'
import { TitleComponent, TooltipComponent, LegendComponent } from 'echarts/components'

echarts.use([RadarChart, CanvasRenderer, TitleComponent, TooltipComponent, LegendComponent])

const profilePercent = ref(0)
const displayedPercent = useTransition(profilePercent, { duration: 1200 })

const radarChartRef = ref<HTMLElement>()
let chartInstance: echarts.ECharts | null = null

const todos = ref([
  { id: 1, text: '完善项目经历描述', priority: 'high', done: false },
  { id: 2, text: '完成性格测评问卷', priority: 'medium', done: false },
  { id: 3, text: '查看新匹配的实习岗位', priority: 'low', done: false },
  { id: 4, text: '预约AI模拟面试', priority: 'info', done: false },
])

const matchedJobs = ref([
  { name: '前端开发工程师', company: '字节跳动', type: '实习', score: 92 },
  { name: '数据分析师', company: '阿里巴巴', type: '校招', score: 87 },
  { name: '产品经理助理', company: '腾讯', type: '实习', score: 79 },
])

const activities = ref([
  { icon: 'DataAnalysis', color: '#6366f1', bg: '#e0e7ff', text: '完成了「Python编程能力」评估', time: '2小时前' },
  { icon: 'Opportunity', color: '#22c55e', bg: '#dcfce7', text: '新增3个匹配岗位', time: '昨天' },
  { icon: 'ChatLineSquare', color: '#f59e0b', bg: '#fef3c7', text: 'AI对话：暑期实习规划讨论', time: '2天前' },
])

const radarData = ref({
  indicators: [
    { name: '专业技术能力', max: 5 },
    { name: '实践经验背景', max: 5 },
    { name: '通用软素质', max: 5 },
    { name: '职业匹配度', max: 5 },
    { name: '成长潜力', max: 5 },
    { name: '基础资质条件', max: 5 },
  ],
  values: [4.0, 3.0, 3.5, 3.5, 4.0, 3.0],
})

function getScoreColor(score: number) {
  if (score >= 90) return { bg: '#dcfce7', color: '#22c55e' }
  if (score >= 80) return { bg: '#e0e7ff', color: '#6366f1' }
  return { bg: '#fef3c7', color: '#f59e0b' }
}

function getPriorityColor(priority: string) {
  const map: Record<string, string> = { high: '#ef4444', medium: '#f59e0b', low: '#6366f1', info: '#94a3b8' }
  return map[priority] || '#94a3b8'
}

function initRadarChart() {
  if (!radarChartRef.value) return
  chartInstance = echarts.init(radarChartRef.value)
  chartInstance.setOption({
    radar: {
      indicator: radarData.value.indicators,
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
        value: radarData.value.values,
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

onMounted(() => {
  profilePercent.value = 68
  initRadarChart()
  if (radarChartRef.value) {
    useResizeObserver(radarChartRef.value, () => chartInstance?.resize())
  }
})
</script>

<template>
  <div class="dash-grid">
    <!-- Profile Completion Ring -->
    <div class="widget hover-lift stagger-item">
      <div class="widget-header">
        <span class="widget-title">画像完成度</span>
        <span class="widget-action">完善 →</span>
      </div>
      <div class="ring-container">
        <svg class="ring-svg" viewBox="0 0 80 80">
          <circle class="ring-bg" cx="40" cy="40" r="36" />
          <circle
            class="ring-fill"
            cx="40" cy="40" r="36"
            :style="{ strokeDashoffset: 226 - (226 * displayedPercent) / 100 }"
          />
        </svg>
        <div class="ring-info">
          <h3>{{ Math.round(displayedPercent) }}%</h3>
          <p>还差几个维度</p>
        </div>
      </div>
    </div>

    <!-- AI Recommendation -->
    <div class="widget ai-card hover-lift stagger-item">
      <div class="widget-header">
        <span class="widget-title">✨ AI 智能推荐</span>
        <span class="widget-action">换一批</span>
      </div>
      <div class="ai-suggestion">
        根据你的能力画像和近期行业动态，建议你关注<strong>前端开发</strong>和<strong>数据分析</strong>方向。
        你已掌握的技能在这些领域有较高需求，建议补充项目实战经验以提升竞争力。
      </div>
      <span class="ai-tag">基于你的最新评估结果</span>
    </div>

    <!-- Todos -->
    <div class="widget hover-lift stagger-item">
      <div class="widget-header">
        <span class="widget-title">待办事项</span>
        <span class="widget-action">+ 添加</span>
      </div>
      <div class="todo-list">
        <div v-for="todo in todos" :key="todo.id" class="todo-item">
          <div class="todo-checkbox" :class="{ done: todo.done }"></div>
          <span class="todo-text">{{ todo.text }}</span>
          <div class="todo-priority" :style="{ background: getPriorityColor(todo.priority) }"></div>
        </div>
      </div>
    </div>

    <!-- Matched Jobs -->
    <div class="widget hover-lift stagger-item">
      <div class="widget-header">
        <span class="widget-title">高匹配岗位</span>
        <span class="widget-action">查看全部 →</span>
      </div>
      <div v-for="job in matchedJobs" :key="job.name" class="job-mini hover-lift">
        <div
          class="match-score"
          :style="{ background: getScoreColor(job.score).bg, color: getScoreColor(job.score).color }"
        >
          {{ job.score }}%
        </div>
        <div class="job-info">
          <div class="job-name">{{ job.name }}</div>
          <div class="job-company">{{ job.company }} · {{ job.type }}</div>
        </div>
      </div>
    </div>

    <!-- Skills Radar -->
    <div class="widget hover-lift stagger-item">
      <div class="widget-header">
        <span class="widget-title">能力雷达图</span>
        <span class="widget-action">详情 →</span>
      </div>
      <div ref="radarChartRef" class="radar-chart"></div>
    </div>

    <!-- Activity Feed -->
    <div class="widget hover-lift stagger-item">
      <div class="widget-header">
        <span class="widget-title">最近动态</span>
        <span class="widget-action">全部</span>
      </div>
      <div v-for="(activity, idx) in activities" :key="idx" class="feed-item">
        <div class="feed-icon" :style="{ background: activity.bg, color: activity.color }">
          <el-icon :size="14"><component :is="activity.icon" /></el-icon>
        </div>
        <div class="feed-content">
          <div class="feed-text">{{ activity.text }}</div>
          <div class="feed-time">{{ activity.time }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dash-grid {
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  gap: var(--space-5);
}
.dash-grid > :nth-child(1) { grid-column: span 3; }
.dash-grid > :nth-child(2) { grid-column: span 6; }
.dash-grid > :nth-child(3) { grid-column: span 3; }
.dash-grid > :nth-child(4) { grid-column: span 4; }
.dash-grid > :nth-child(5) { grid-column: span 4; }
.dash-grid > :nth-child(6) { grid-column: span 4; }

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
.widget-action {
  font-size: 12px;
  color: var(--c-brand);
  cursor: pointer;
  transition: opacity var(--duration-fast) ease;
}
.widget-action:hover {
  opacity: 0.7;
}

/* Ring */
.ring-container {
  display: flex;
  align-items: center;
  gap: var(--space-5);
}
.ring-svg {
  width: 80px;
  height: 80px;
  transform: rotate(-90deg);
}
.ring-bg {
  fill: none;
  stroke: var(--c-bg-soft);
  stroke-width: 8;
}
.ring-fill {
  fill: none;
  stroke: var(--c-brand);
  stroke-width: 8;
  stroke-linecap: round;
  stroke-dasharray: 226;
  transition: stroke-dashoffset 0.1s linear;
}
.ring-info h3 {
  font-size: 28px;
  font-weight: 700;
  color: var(--c-text-1);
}
.ring-info p {
  font-size: 13px;
  color: var(--c-text-3);
  margin-top: var(--space-1);
}

/* AI Card */
.ai-card {
  background: var(--c-brand-gradient);
  border: none;
  color: #fff;
}
.ai-card .widget-title { color: #fff; }
.ai-card .widget-action { color: rgba(255, 255, 255, 0.8); }
.ai-suggestion {
  font-size: 14px;
  line-height: 1.8;
  opacity: 0.95;
}
.ai-tag {
  display: inline-block;
  padding: 2px 10px;
  border-radius: var(--radius-full);
  background: rgba(255, 255, 255, 0.2);
  font-size: 12px;
  margin-top: var(--space-3);
}

/* Todos */
.todo-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.todo-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  transition: background var(--duration-fast) ease;
  cursor: pointer;
}
.todo-item:hover {
  background: var(--c-bg-soft);
}
.todo-checkbox {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: 2px solid var(--c-bg-mute);
  flex-shrink: 0;
  transition: all var(--duration-fast) ease;
}
.todo-checkbox.done {
  background: var(--c-brand);
  border-color: var(--c-brand);
}
.todo-text {
  font-size: 13px;
  color: var(--c-text-2);
  flex: 1;
}
.todo-priority {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

/* Job Mini */
.job-mini {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  border-radius: var(--radius-sm);
  border: 1px solid var(--c-bg-mute);
  margin-bottom: var(--space-2);
  cursor: pointer;
}
.job-mini:last-child { margin-bottom: 0; }
.job-mini:hover {
  border-color: var(--c-brand);
  background: var(--c-brand-lighter);
}
.match-score {
  width: 44px;
  height: 44px;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
  flex-shrink: 0;
}
.job-info { flex: 1; }
.job-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--c-text-1);
}
.job-company {
  font-size: 12px;
  color: var(--c-text-3);
  margin-top: 2px;
}

/* Radar Chart */
.radar-chart {
  height: 200px;
  width: 100%;
}

/* Feed */
.feed-item {
  display: flex;
  gap: var(--space-3);
  padding: var(--space-3) 0;
}
.feed-item:not(:last-child) {
  border-bottom: 1px solid var(--c-bg-soft);
}
.feed-icon {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.feed-content { flex: 1; }
.feed-text {
  font-size: 13px;
  color: var(--c-text-1);
  line-height: 1.5;
}
.feed-time {
  font-size: 11px;
  color: var(--c-text-3);
  margin-top: 2px;
}
</style>
