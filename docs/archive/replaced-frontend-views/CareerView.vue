<script setup lang="ts">
/**
 * 成长路径页面
 * 展示职业路线规划、里程碑时间线、成长计划、学习资源
 * 调用的后端API：
 *   - GET  /api/v1/resume/latest              获取最新简历状态（含 profile_id）
 *   - GET  /api/v1/admin/jobs                 获取岗位列表（用于选择目标岗位）
 *   - POST /api/v1/career/paths               生成职业路线
 *   - GET  /api/v1/career/paths               获取职业路线列表
 *   - GET  /api/v1/career/paths/{path_id}     获取职业路线详情
 *   - POST /api/v1/career/plans               生成成长计划
 *   - GET  /api/v1/career/plans               获取成长计划列表
 * 调用的Agent：LangGraph Agent（后端 path_planner 调用 LLM 生成路线和计划）
 */
import { ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import {
  TrendCharts,
  Loading,
  Warning,
  Aim,
  Flag,
  Collection,
  Reading,
  Timer,
  Promotion,
  Trophy,
  Document,
} from '@element-plus/icons-vue'
import { careerApi, type CareerPathResponse, type GrowthPlanResponse } from '../../api/career'
import { profileApi, type ResumeStatusResponse } from '../../api/profile'
import { jobsApi, type JobProfileResponse } from '../../api/jobs'

// ==================== 状态 ====================

const loading = ref(false)
const generating = ref(false)
const resumeStatus = ref<ResumeStatusResponse | null>(null)
const jobList = ref<JobProfileResponse[]>([])
const careerPaths = ref<CareerPathResponse[]>([])
const growthPlans = ref<GrowthPlanResponse[]>([])
const activePath = ref<CareerPathResponse | null>(null)
const activeTab = ref<'paths' | 'plans'>('paths')

// 生成路线参数
const selectedJobId = ref<number | null>(null)
const currentStage = ref('在校学生')

// 生成计划参数
const weeklyHours = ref(10)
const cycleWeeks = ref(12)

// ==================== 计算属性 ====================

const hasProfile = computed(() => {
  return resumeStatus.value?.profile_id != null
})

const profileId = computed(() => {
  return resumeStatus.value?.profile_id
})

const activePathPlans = computed(() => {
  if (!activePath.value) return []
  return growthPlans.value.filter(p => p.growth_path_id === activePath.value!.id)
})

// ==================== 方法 ====================

async function loadResumeStatus() {
  try {
    const latest = await profileApi.getLatestResume()
    resumeStatus.value = latest
  } catch {
    resumeStatus.value = null
  }
}

async function loadJobs() {
  try {
    const res = await jobsApi.getList({ limit: 50 })
    jobList.value = res.items
  } catch {
    // 岗位列表加载失败不影响主流程
  }
}

async function loadCareerPaths() {
  try {
    const res = await careerApi.getPaths({ limit: 20 })
    careerPaths.value = res.items
    if (res.items.length > 0 && !activePath.value) {
      activePath.value = res.items[0]
    }
  } catch {
    // 加载失败不影响
  }
}

async function loadGrowthPlans() {
  try {
    const res = await careerApi.getPlans({ limit: 20 })
    growthPlans.value = res.items
  } catch {
    // 加载失败不影响
  }
}

async function generatePath() {
  if (!profileId.value) {
    ElMessage.warning('请先上传简历并完成解析')
    return
  }
  if (!selectedJobId.value) {
    ElMessage.warning('请选择目标岗位')
    return
  }

  generating.value = true
  try {
    const result = await careerApi.generatePath({
      profile_id: profileId.value,
      target_job_id: selectedJob_id.value,
      current_stage: currentStage.value,
    })
    careerPaths.value.unshift(result)
    activePath.value = result
    ElMessage.success('职业路线生成成功')
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || '生成职业路线失败')
  } finally {
    generating.value = false
  }
}

async function generatePlan() {
  if (!activePath.value) {
    ElMessage.warning('请先生成或选择职业路线')
    return
  }

  generating.value = true
  try {
    const result = await careerApi.generatePlan({
      growth_path_id: activePath.value.id,
      weekly_hours: weeklyHours.value,
      cycle_weeks: cycleWeeks.value,
    })
    growthPlans.value.unshift(result)
    activeTab.value = 'plans'
    ElMessage.success('成长计划生成成功')
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || '生成成长计划失败')
  } finally {
    generating.value = false
  }
}

function selectPath(path: CareerPathResponse) {
  activePath.value = path
  activeTab.value = 'plans'
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

function getMilestones(path: CareerPathResponse): any[] {
  if (!path.milestones) return []
  if (Array.isArray(path.milestones)) return path.milestones
  return []
}

function getLearningResources(path: CareerPathResponse): any {
  if (!path.learning_resources) return {}
  if (typeof path.learning_resources === 'object') return path.learning_resources
  return {}
}

function getTasks(plan: GrowthPlanResponse): any[] {
  if (!plan.tasks) return []
  if (Array.isArray(plan.tasks)) return plan.tasks
  return []
}

// ==================== 生命周期 ====================

onMounted(async () => {
  loading.value = true
  await Promise.all([
    loadResumeStatus(),
    loadJobs(),
    loadCareerPaths(),
    loadGrowthPlans(),
  ])
  loading.value = false
})
</script>

<template>
  <div class="career-page">
    <!-- 加载状态 -->
    <div v-if="loading" class="loading-container">
      <el-icon :size="32" class="is-loading" color="var(--c-brand)"><Loading /></el-icon>
      <p>正在加载成长路径数据...</p>
    </div>

    <!-- 空状态：无画像 -->
    <div v-else-if="!hasProfile" class="empty-state">
      <el-icon :size="48" color="var(--c-text-3)"><Warning /></el-icon>
      <h3>暂无能力画像</h3>
      <p>请先上传简历并完成解析，才能生成职业路线</p>
      <el-button type="primary" @click="$router.push('/resume')">前往上传简历</el-button>
    </div>

    <!-- 主要内容 -->
    <div v-else class="career-content">
      <!-- 路线生成面板 -->
      <div class="widget generate-panel">
        <div class="widget-header">
          <div class="header-left">
            <el-icon :size="18" color="var(--c-brand)"><Aim /></el-icon>
            <span class="widget-title">生成职业路线</span>
          </div>
          <span class="profile-badge">画像 #{{ profileId }}</span>
        </div>
        <div class="generate-body">
          <div class="form-row">
            <div class="form-item">
              <label class="form-label">目标岗位 *</label>
              <el-select
                v-model="selectedJobId"
                placeholder="请选择目标岗位"
                filterable
                clearable
                style="width: 100%"
              >
                <el-option
                  v-for="job in jobList"
                  :key="job.id"
                  :label="job.title || `岗位 #${job.id}`"
                  :value="job.id"
                >
                  <span>{{ job.title || `岗位 #${job.id}` }}</span>
                  <span v-if="job.industry" class="job-option-meta">{{ job.industry }}</span>
                </el-option>
              </el-select>
            </div>
            <div class="form-item">
              <label class="form-label">当前阶段</label>
              <el-select v-model="currentStage" style="width: 100%">
                <el-option label="在校学生" value="在校学生" />
                <el-option label="应届生" value="应届生" />
                <el-option label="实习中" value="实习中" />
                <el-option label="职场新人(0-1年)" value="职场新人" />
              </el-select>
            </div>
          </div>
          <div class="form-actions">
            <el-button
              type="primary"
              :loading="generating"
              :icon="Promotion"
              @click="generatePath"
            >
              {{ generating ? '生成中...' : '生成职业路线' }}
            </el-button>
            <span class="form-hint">基于画像匹配结果，AI 为你规划最优职业发展路径</span>
          </div>
        </div>
      </div>

      <!-- Tab 切换 -->
      <div class="content-tabs">
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'paths' }"
          @click="activeTab = 'paths'"
        >
          <el-icon :size="15"><Flag /></el-icon>
          职业路线
          <span class="tab-count" v-if="careerPaths.length">{{ careerPaths.length }}</span>
        </button>
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'plans' }"
          @click="activeTab = 'plans'"
        >
          <el-icon :size="15"><Timer /></el-icon>
          成长计划
          <span class="tab-count" v-if="growthPlans.length">{{ growthPlans.length }}</span>
        </button>
      </div>

      <!-- 职业路线内容 -->
      <div v-if="activeTab === 'paths'" class="tab-content">
        <!-- 路线列表为空 -->
        <div v-if="careerPaths.length === 0" class="no-data-card">
          <el-icon :size="36" color="var(--c-text-3)"><TrendCharts /></el-icon>
          <p>暂无职业路线，请先生成一条职业路径</p>
        </div>

        <!-- 路线卡片列表 -->
        <div v-else class="paths-grid">
          <div
            v-for="path in careerPaths"
            :key="path.id"
            class="path-card"
            :class="{ active: activePath?.id === path.id }"
            @click="selectPath(path)"
          >
            <div class="path-header">
              <h3 class="path-title">
                {{ path.target_position || '职业发展路径' }}
              </h3>
              <el-tag v-if="path.path_type" size="small" effect="plain" type="primary">
                {{ path.path_type }}
              </el-tag>
            </div>
            <div class="path-meta">
              <span>创建于 {{ formatDate(path.created_at) }}</span>
              <span v-if="getMilestones(path).length">
                {{ getMilestones(path).length }} 个里程碑
              </span>
            </div>

            <!-- 里程碑预览 -->
            <div v-if="getMilestones(path).length > 0" class="milestones-preview">
              <div
                v-for="(ms, idx) in getMilestones(path).slice(0, 3)"
                :key="idx"
                class="milestone-dot"
              >
                <div class="dot"></div>
                <span class="ms-stage">{{ ms.stage }}</span>
                <span class="ms-month">{{ ms.duration_months }}个月</span>
              </div>
              <div v-if="getMilestones(path).length > 3" class="more-milestones">
                +{{ getMilestones(path).length - 3 }} 更多
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 成长计划内容 -->
      <div v-if="activeTab === 'plans'" class="tab-content">
        <!-- 计划生成面板 -->
        <div v-if="activePath" class="widget plan-panel">
          <div class="widget-header">
            <div class="header-left">
              <el-icon :size="16" color="var(--c-brand)"><Timer /></el-icon>
              <span class="widget-title">生成成长计划</span>
            </div>
            <span class="path-name">路线: {{ activePath.target_position || '#' + activePath.id }}</span>
          </div>
          <div class="plan-controls">
            <div class="control-group">
              <label>每周可用时间</label>
              <el-slider v-model="weeklyHours" :min="1" :max="40" show-input :show-input-controls="false" />
              <span class="control-val">{{ weeklyHours }}h</span>
            </div>
            <div class="control-group">
              <label>计划周期</label>
              <el-slider v-model="cycleWeeks" :min="4" :max="52" :step="4" show-input :show-input-controls="false" />
              <span class="control-val">{{ cycleWeeks }}周</span>
            </div>
            <el-button
              type="primary"
              size="small"
              :loading="generating"
              @click="generatePlan"
            >
              生成计划
            </el-button>
          </div>
        </div>

        <!-- 无计划提示 -->
        <div v-if="activePathPlans.length === 0 && !generating" class="no-data-card">
          <el-icon :size="36" color="var(--c-text-3)"><Timer /></el-icon>
          <p v-if="!activePath">请先选择一条职业路线</p>
          <p v-else>暂无成长计划，点击上方按钮生成</p>
        </div>

        <!-- 计划列表 -->
        <div v-if="activePathPlans.length > 0" class="plans-list">
          <div
            v-for="plan in activePathPlans"
            :key="plan.id"
            class="plan-card"
          >
            <div class="plan-header">
              <div class="plan-info">
                <h4 class="plan-title">成长计划 #{{ plan.id }}</h4>
                <div class="plan-tags">
                  <el-tag v-if="plan.cycle_weeks" size="small" effect="plain">
                    {{ plan.cycle_weeks }}周
                  </el-tag>
                  <el-tag v-if="plan.intensity" size="small" type="warning" effect="plain">
                    {{ plan.intensity }}强度
                  </el-tag>
                </div>
              </div>
              <span class="plan-date">{{ formatDate(plan.created_at) }}</span>
            </div>

            <!-- 任务时间线 -->
            <div v-if="getTasks(plan).length > 0" class="tasks-timeline">
              <div
                v-for="(task, idx) in getTasks(plan)"
                :key="idx"
                class="task-item"
              >
                <div class="task-dot"></div>
                <div class="task-content">
                  <div class="task-header">
                    <span class="task-week">{{ task.week || `第${idx + 1}周` }}</span>
                    <span class="task-title">{{ task.title }}</span>
                    <span v-if="task.time_hours" class="task-time">{{ task.time_hours }}h</span>
                  </div>
                  <p v-if="task.description" class="task-desc">{{ task.description }}</p>
                  <div v-if="task.deliverables && task.deliverables.length" class="task-deliverables">
                    <span
                      v-for="d in task.deliverables"
                      :key="d"
                      class="deliverable-tag"
                    >
                      {{ d }}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 里程碑详细时间线（当选中路线时显示） -->
      <div v-if="activePath && getMilestones(activePath).length > 0" class="widget timeline-widget">
        <div class="widget-header">
          <div class="header-left">
            <el-icon :size="16" color="var(--c-brand)"><Flag /></el-icon>
            <span class="widget-title">里程碑规划</span>
          </div>
          <span class="target-label">{{ activePath.target_position || '职业发展' }}</span>
        </div>
        <div class="timeline-container">
          <div
            v-for="(ms, idx) in getMilestones(activePath)"
            :key="idx"
            class="timeline-item"
          >
            <div class="timeline-marker">
              <div class="timeline-dot"></div>
              <div v-if="idx < getMilestones(activePath).length - 1" class="timeline-line"></div>
            </div>
            <div class="timeline-content">
              <div class="ms-header">
                <span class="ms-stage-name">{{ ms.stage || `阶段 ${idx + 1}` }}</span>
                <span class="ms-duration">
                  <el-icon :size="12"><Timer /></el-icon>
                  {{ ms.duration_months }} 个月
                </span>
              </div>
              <div v-if="ms.goals && ms.goals.length" class="ms-goals">
                <div class="ms-section-label">目标</div>
                <ul>
                  <li v-for="goal in ms.goals" :key="goal">{{ goal }}</li>
                </ul>
              </div>
              <div v-if="ms.key_actions && ms.key_actions.length" class="ms-actions">
                <div class="ms-section-label">关键行动</div>
                <ul>
                  <li v-for="action in ms.key_actions" :key="action">{{ action }}</li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 学习资源 -->
      <div v-if="activePath && Object.keys(getLearningResources(activePath)).length > 0" class="widget resources-widget">
        <div class="widget-header">
          <div class="header-left">
            <el-icon :size="16" color="var(--c-brand)"><Collection /></el-icon>
            <span class="widget-title">学习资源</span>
          </div>
        </div>
        <div class="resources-grid">
          <template v-if="getLearningResources(activePath).courses">
            <div class="resource-section">
              <div class="resource-header">
                <el-icon :size="14"><Reading /></el-icon>
                <span>推荐课程</span>
              </div>
              <div class="resource-items">
                <span
                  v-for="item in getLearningResources(activePath).courses"
                  :key="item"
                  class="resource-tag"
                >
                  {{ item }}
                </span>
              </div>
            </div>
          </template>
          <template v-if="getLearningResources(activePath).certificates">
            <div class="resource-section">
              <div class="resource-header">
                <el-icon :size="14"><Trophy /></el-icon>
                <span>推荐证书</span>
              </div>
              <div class="resource-items">
                <span
                  v-for="item in getLearningResources(activePath).certificates"
                  :key="item"
                  class="resource-tag"
                >
                  {{ item }}
                </span>
              </div>
            </div>
          </template>
          <template v-if="getLearningResources(activePath).books">
            <div class="resource-section">
              <div class="resource-header">
                <el-icon :size="14"><Document /></el-icon>
                <span>推荐书籍</span>
              </div>
              <div class="resource-items">
                <span
                  v-for="item in getLearningResources(activePath).books"
                  :key="item"
                  class="resource-tag"
                >
                  {{ item }}
                </span>
              </div>
            </div>
          </template>
          <template v-if="getLearningResources(activePath).projects">
            <div class="resource-section">
              <div class="resource-header">
                <el-icon :size="14"><Aim /></el-icon>
                <span>实践项目</span>
              </div>
              <div class="resource-items">
                <span
                  v-for="item in getLearningResources(activePath).projects"
                  :key="item"
                  class="resource-tag"
                >
                  {{ item }}
                </span>
              </div>
            </div>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.career-page {
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
  margin-bottom: var(--space-5);
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
.profile-badge,
.path-name,
.target-label {
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
  gap: var(--space-4);
}
.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-4);
}
.form-item {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.form-label {
  font-size: 13px;
  color: var(--c-text-2);
  font-weight: 500;
}
.job-option-meta {
  float: right;
  font-size: 12px;
  color: var(--c-text-3);
}
.form-actions {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding-top: var(--space-3);
  border-top: 1px solid var(--c-bg-mute);
}
.form-hint {
  font-size: 12px;
  color: var(--c-text-3);
}

/* Tab 切换 */
.content-tabs {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
  border-bottom: 1px solid var(--c-bg-mute);
  padding-bottom: var(--space-3);
}
.tab-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 16px;
  border-radius: var(--radius-full);
  border: 1px solid var(--c-bg-mute);
  background: var(--c-surface);
  color: var(--c-text-2);
  font-size: 13px;
  cursor: pointer;
  transition: all var(--duration-fast) ease;
}
.tab-btn:hover {
  border-color: var(--c-brand);
  color: var(--c-brand);
}
.tab-btn.active {
  background: var(--c-brand-lighter);
  border-color: var(--c-brand);
  color: var(--c-brand);
  font-weight: 500;
}
.tab-count {
  font-size: 11px;
  padding: 0 6px;
  border-radius: var(--radius-full);
  background: var(--c-bg-soft);
  color: var(--c-text-3);
}

/* 无数据卡片 */
.no-data-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 150px;
  gap: var(--space-3);
  color: var(--c-text-3);
  font-size: 14px;
  background: var(--c-surface);
  border-radius: var(--radius-md);
  border: 1px dashed var(--c-bg-mute);
  padding: var(--space-6);
}

/* 路线卡片 Grid */
.paths-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-4);
}
.path-card {
  background: var(--c-surface);
  border-radius: var(--radius-md);
  padding: var(--space-4);
  border: 1px solid var(--c-bg-mute);
  box-shadow: var(--shadow-xs);
  cursor: pointer;
  transition: all var(--duration-fast) ease;
}
.path-card:hover {
  box-shadow: var(--shadow-md);
  border-color: var(--c-brand-lighter);
}
.path-card.active {
  border-color: var(--c-brand);
  box-shadow: 0 0 0 1px var(--c-brand);
}
.path-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}
.path-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--c-text-1);
  margin: 0;
}
.path-meta {
  display: flex;
  gap: var(--space-3);
  font-size: 12px;
  color: var(--c-text-3);
  margin-bottom: var(--space-3);
}

/* 里程碑预览 */
.milestones-preview {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.milestone-dot {
  display: flex;
  align-items: center;
  gap: 4px;
}
.milestone-dot .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--c-brand);
}
.ms-stage {
  font-size: 12px;
  color: var(--c-text-2);
}
.ms-month {
  font-size: 11px;
  color: var(--c-text-3);
}
.more-milestones {
  font-size: 11px;
  color: var(--c-brand);
  cursor: pointer;
}

/* 计划生成面板 */
.plan-panel {
  margin-bottom: var(--space-4);
}
.plan-controls {
  display: flex;
  align-items: flex-end;
  gap: var(--space-5);
}
.control-group {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.control-group label {
  font-size: 13px;
  color: var(--c-text-2);
}
.control-val {
  font-size: 12px;
  color: var(--c-text-3);
}

/* 计划列表 */
.plans-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.plan-card {
  background: var(--c-surface);
  border-radius: var(--radius-md);
  padding: var(--space-5);
  border: 1px solid var(--c-bg-mute);
  box-shadow: var(--shadow-xs);
}
.plan-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: var(--space-4);
}
.plan-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--c-text-1);
  margin: 0 0 var(--space-2) 0;
}
.plan-tags {
  display: flex;
  gap: var(--space-1);
}
.plan-date {
  font-size: 12px;
  color: var(--c-text-3);
}

/* 任务时间线 */
.tasks-timeline {
  position: relative;
  padding-left: 20px;
}
.task-item {
  display: flex;
  gap: var(--space-3);
  position: relative;
  padding-bottom: var(--space-4);
}
.task-item:last-child {
  padding-bottom: 0;
}
.task-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--c-brand);
  flex-shrink: 0;
  margin-top: 4px;
  position: relative;
  z-index: 1;
}
.task-item::before {
  content: '';
  position: absolute;
  left: 4.5px;
  top: 14px;
  bottom: -14px;
  width: 1px;
  background: var(--c-bg-mute);
}
.task-item:last-child::before {
  display: none;
}
.task-content {
  flex: 1;
}
.task-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-1);
}
.task-week {
  font-size: 11px;
  color: var(--c-brand);
  font-weight: 600;
  background: var(--c-brand-lighter);
  padding: 1px 6px;
  border-radius: var(--radius-sm);
}
.task-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--c-text-1);
}
.task-time {
  font-size: 11px;
  color: var(--c-text-3);
  margin-left: auto;
}
.task-desc {
  font-size: 12px;
  color: var(--c-text-3);
  line-height: 1.5;
  margin: var(--space-1) 0 0 0;
}
.task-deliverables {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: var(--space-2);
}
.deliverable-tag {
  font-size: 11px;
  padding: 1px 8px;
  border-radius: var(--radius-sm);
  background: var(--c-bg-soft);
  color: var(--c-text-2);
}

/* 里程碑详细时间线 */
.timeline-container {
  padding-left: 8px;
}
.timeline-item {
  display: flex;
  gap: var(--space-4);
  position: relative;
}
.timeline-marker {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex-shrink: 0;
  width: 16px;
}
.timeline-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--c-brand);
  border: 2px solid var(--c-brand-lighter);
  flex-shrink: 0;
}
.timeline-line {
  width: 2px;
  flex: 1;
  background: var(--c-bg-mute);
  margin: var(--space-1) 0;
}
.timeline-content {
  flex: 1;
  padding-bottom: var(--space-5);
}
.ms-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-2);
}
.ms-stage-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--c-text-1);
}
.ms-duration {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--c-text-3);
}
.ms-goals,
.ms-actions {
  margin-top: var(--space-2);
}
.ms-section-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--c-text-2);
  margin-bottom: var(--space-1);
}
.ms-goals ul,
.ms-actions ul {
  margin: 0;
  padding-left: 18px;
}
.ms-goals li,
.ms-actions li {
  font-size: 13px;
  color: var(--c-text-2);
  line-height: 1.6;
}

/* 学习资源 */
.resources-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-4);
}
.resource-section {
  background: var(--c-bg-soft);
  border-radius: var(--radius-sm);
  padding: var(--space-3) var(--space-4);
}
.resource-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 500;
  color: var(--c-text-2);
  margin-bottom: var(--space-2);
}
.resource-items {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.resource-tag {
  font-size: 12px;
  padding: 2px 10px;
  border-radius: var(--radius-sm);
  background: var(--c-surface);
  color: var(--c-text-2);
  border: 1px solid var(--c-bg-mute);
}

/* 响应式 */
@media (max-width: 768px) {
  .form-row {
    grid-template-columns: 1fr;
  }
  .plan-controls {
    flex-direction: column;
    gap: var(--space-3);
  }
  .paths-grid {
    grid-template-columns: 1fr;
  }
  .resources-grid {
    grid-template-columns: 1fr;
  }
}
</style>
