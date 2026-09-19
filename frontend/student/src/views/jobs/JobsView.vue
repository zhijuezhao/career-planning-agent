<script setup lang="ts">
/**
 * 职位搜索页面
 * 展示岗位列表、搜索筛选、岗位详情
 * 调用的后端API：
 *   - GET /api/v1/admin/jobs         获取岗位列表（支持分页、筛选）
 *   - GET /api/v1/admin/jobs/{id}    获取岗位详情
 * 注意：当前使用 admin 端点，需后端添加学生端公开 /jobs 接口
 */
import { ref, onMounted, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Search,
  Filter,
  Money,
  OfficeBuilding,
  Clock,
  View,
  Loading,
} from '@element-plus/icons-vue'
import { jobsApi, type JobProfileResponse, type JobListParams } from '../../api/jobs'

// ==================== 状态 ====================

const loading = ref(false)
const jobList = ref<JobProfileResponse[]>([])
const total = ref(0)
const selectedJob = ref<JobProfileResponse | null>(null)
const showDetail = ref(false)

// 搜索筛选参数
const keyword = ref('')
const industry = ref('')
const level = ref('')
const pagination = ref({ skip: 0, limit: 12 })
const debounceTimer = ref<any>(null)

// ==================== 计算属性 ====================

const industryOptions = computed(() => {
  const set = new Set<string>()
  jobList.value.forEach(j => {
    if (j.industry) set.add(j.industry)
  })
  return Array.from(set)
})

const levelOptions = computed(() => {
  const set = new Set<string>()
  jobList.value.forEach(j => {
    if (j.level) set.add(j.level)
  })
  return Array.from(set)
})

const totalPages = computed(() => Math.ceil(total.value / pagination.value.limit))

// ==================== 方法 ====================

async function loadJobs() {
  loading.value = true
  try {
    const params: JobListParams = {
      skip: pagination.value.skip,
      limit: pagination.value.limit,
      keyword: keyword.value || undefined,
      industry: industry.value || undefined,
      level: level.value || undefined,
    }
    const res = await jobsApi.getList(params)
    jobList.value = res.items
    total.value = res.total
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || '加载岗位列表失败')
  } finally {
    loading.value = false
  }
}

function debouncedSearch() {
  if (debounceTimer.value) clearTimeout(debounceTimer.value)
  debounceTimer.value = setTimeout(() => {
    pagination.value.skip = 0
    loadJobs()
  }, 300)
}

function resetFilters() {
  keyword.value = ''
  industry.value = ''
  level.value = ''
  pagination.value.skip = 0
  loadJobs()
}

function goPage(page: number) {
  pagination.value.skip = page * pagination.value.limit
  loadJobs()
}

function viewDetail(job: JobProfileResponse) {
  selectedJob.value = job
  showDetail.value = true
}

function formatDate(dateStr: string): string {
  if (!dateStr) return '—'
  return new Date(dateStr).toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

function getSkillTags(job: JobProfileResponse): string[] {
  const tags: string[] = []
  if (job.hard_skills) {
    if (typeof job.hard_skills === 'object' && job.hard_skills.tags) {
      tags.push(...job.hard_skills.tags.slice(0, 5))
    } else if (Array.isArray(job.hard_skills)) {
      tags.push(...job.hard_skills.slice(0, 5))
    }
  }
  if (job.soft_skills) {
    if (typeof job.soft_skills === 'object' && job.soft_skills.tags) {
      tags.push(...job.soft_skills.tags.slice(0, 3))
    } else if (Array.isArray(job.soft_skills)) {
      tags.push(...job.soft_skills.slice(0, 3))
    }
  }
  return tags
}

// 监听筛选变化
watch([industry, level], () => {
  pagination.value.skip = 0
  loadJobs()
})

// ==================== 生命周期 ====================

onMounted(() => {
  loadJobs()
})
</script>

<template>
  <div class="jobs-page">
    <!-- 搜索栏 -->
    <div class="widget search-bar">
      <div class="search-row">
        <el-input
          v-model="keyword"
          placeholder="搜索岗位名称、技能、行业..."
          clearable
          :prefix-icon="Search"
          size="large"
          @input="debouncedSearch"
        />
        <el-button type="primary" size="large" :loading="loading" @click="loadJobs">
          搜索
        </el-button>
      </div>
      <div class="filter-row">
        <div class="filter-item">
          <el-icon :size="14"><Filter /></el-icon>
          <span class="filter-label">行业</span>
          <el-select v-model="industry" placeholder="全部行业" clearable size="small">
            <el-option
              v-for="opt in industryOptions"
              :key="opt"
              :label="opt"
              :value="opt"
            />
          </el-select>
        </div>
        <div class="filter-item">
          <span class="filter-label">级别</span>
          <el-select v-model="level" placeholder="全部级别" clearable size="small">
            <el-option
              v-for="opt in levelOptions"
              :key="opt"
              :label="opt"
              :value="opt"
            />
          </el-select>
        </div>
        <el-button v-if="industry || level" text size="small" @click="resetFilters">
          清除筛选
        </el-button>
        <span class="result-count">共 {{ total }} 个岗位</span>
      </div>
    </div>

    <!-- 主体区域 -->
    <div class="jobs-main">
      <!-- 岗位列表 -->
      <div class="jobs-list-section">
        <!-- 加载状态 -->
        <div v-if="loading && jobList.length === 0" class="list-loading">
          <el-icon :size="28" class="is-loading" color="var(--c-brand)"><Loading /></el-icon>
          <p>正在加载岗位...</p>
        </div>

        <!-- 空结果 -->
        <div v-else-if="!loading && jobList.length === 0" class="list-empty">
          <el-icon :size="40" color="var(--c-text-3)"><Search /></el-icon>
          <p>未找到匹配的岗位</p>
          <el-button text type="primary" @click="resetFilters">清除筛选条件</el-button>
        </div>

        <!-- 岗位卡片列表 -->
        <div v-else class="jobs-grid">
          <div
            v-for="job in jobList"
            :key="job.id"
            class="job-card"
            :class="{ selected: selectedJob?.id === job.id }"
            @click="viewDetail(job)"
          >
            <div class="card-top">
              <h3 class="job-title">{{ job.title || '未命名岗位' }}</h3>
              <div class="job-tags">
                <el-tag v-if="job.industry" size="small" effect="plain">{{ job.industry }}</el-tag>
                <el-tag v-if="job.level" size="small" type="success" effect="plain">{{ job.level }}</el-tag>
              </div>
            </div>

            <div class="job-info-row">
              <div v-if="job.salary_range" class="info-pill">
                <el-icon :size="12"><Money /></el-icon>
                {{ job.salary_range }}
              </div>
              <div v-if="job.education_requirement" class="info-pill">
                <el-icon :size="12"><OfficeBuilding /></el-icon>
                {{ job.education_requirement }}
              </div>
            </div>

            <!-- 技能标签 -->
            <div v-if="getSkillTags(job).length > 0" class="skill-tags">
              <span
                v-for="tag in getSkillTags(job)"
                :key="tag"
                class="skill-tag"
              >
                {{ tag }}
              </span>
            </div>

            <!-- 摘要 -->
            <p v-if="job.summary" class="job-summary">{{ job.summary }}</p>

            <div class="card-footer">
              <span class="update-time">
                <el-icon :size="10"><Clock /></el-icon>
                {{ formatDate(job.updated_at) }}
              </span>
              <el-button text type="primary" size="small" :icon="View">
                查看详情
              </el-button>
            </div>
          </div>
        </div>

        <!-- 分页 -->
        <div v-if="totalPages > 1" class="pagination">
          <el-pagination
            :current-page="Math.floor(pagination.skip / pagination.limit) + 1"
            :page-size="pagination.limit"
            :total="total"
            layout="prev, pager, next, jumper"
            @current-change="(page: number) => goPage(page - 1)"
          />
        </div>
      </div>

      <!-- 岗位详情侧边栏 -->
      <transition name="slide-fade">
        <div v-if="showDetail && selectedJob" class="job-detail-panel">
          <div class="detail-header">
            <h3>{{ selectedJob.title || '岗位详情' }}</h3>
            <el-button text :icon="View" @click="showDetail = false">关闭</el-button>
          </div>

          <div class="detail-body">
            <!-- 基本信息 -->
            <div class="detail-section">
              <div class="detail-tags">
                <el-tag v-if="selectedJob.industry" effect="plain">{{ selectedJob.industry }}</el-tag>
                <el-tag v-if="selectedJob.level" type="success" effect="plain">{{ selectedJob.level }}</el-tag>
              </div>
            </div>

            <!-- 薪资/学历/经验 -->
            <div class="detail-section">
              <h4 class="section-label">基本要求</h4>
              <div class="detail-grid">
                <div v-if="selectedJob.salary_range" class="detail-item">
                  <span class="item-label">薪资范围</span>
                  <span class="item-value salary">{{ selectedJob.salary_range }}</span>
                </div>
                <div v-if="selectedJob.education_requirement" class="detail-item">
                  <span class="item-label">学历要求</span>
                  <span class="item-value">{{ selectedJob.education_requirement }}</span>
                </div>
                <div v-if="selectedJob.experience_requirement" class="detail-item">
                  <span class="item-label">经验要求</span>
                  <span class="item-value">{{ selectedJob.experience_requirement }}</span>
                </div>
              </div>
            </div>

            <!-- 技能要求 -->
            <div v-if="getSkillTags(selectedJob).length > 0" class="detail-section">
              <h4 class="section-label">技能要求</h4>
              <div class="detail-skills">
                <span
                  v-for="tag in getSkillTags(selectedJob)"
                  :key="tag"
                  class="detail-skill-tag"
                >
                  {{ tag }}
                </span>
              </div>
            </div>

            <!-- 岗位描述 -->
            <div v-if="selectedJob.summary" class="detail-section">
              <h4 class="section-label">岗位描述</h4>
              <p class="detail-summary">{{ selectedJob.summary }}</p>
            </div>

            <!-- 职业发展 -->
            <div v-if="selectedJob.career_path" class="detail-section">
              <h4 class="section-label">职业发展</h4>
              <div class="detail-career">
                <pre>{{ JSON.stringify(selectedJob.career_path, null, 2) }}</pre>
              </div>
            </div>

            <!-- 能力要求强度 -->
            <div v-if="selectedJob.requirement_intensity" class="detail-section">
              <h4 class="section-label">能力要求强度</h4>
              <div class="detail-intensity">
                <div
                  v-for="(val, key) in selectedJob.requirement_intensity"
                  :key="key"
                  class="intensity-item"
                >
                  <span class="intensity-label">{{ key }}</span>
                  <div class="intensity-bar-bg">
                    <div
                      class="intensity-bar-fill"
                      :style="{ width: `${((typeof val === 'object' ? val.score || 0 : val) / 5) * 100}%` }"
                    ></div>
                  </div>
                </div>
              </div>
            </div>

            <!-- 岗位展望 -->
            <div v-if="selectedJob.outlook" class="detail-section">
              <h4 class="section-label">岗位展望</h4>
              <p class="detail-summary">{{ typeof selectedJob.outlook === 'string' ? selectedJob.outlook : JSON.stringify(selectedJob.outlook) }}</p>
            </div>

            <!-- 元信息 -->
            <div class="detail-footer">
              <span>创建于 {{ formatDate(selectedJob.created_at) }}</span>
              <span>更新于 {{ formatDate(selectedJob.updated_at) }}</span>
            </div>
          </div>
        </div>
      </transition>
    </div>
  </div>
</template>

<style scoped>
.jobs-page {
  max-width: 1200px;
  margin: 0 auto;
}

/* 通用 Widget */
.widget {
  background: var(--c-surface);
  border-radius: var(--radius-md);
  padding: var(--space-5);
  border: 1px solid var(--c-bg-mute);
  box-shadow: var(--shadow-xs);
}

/* 搜索栏 */
.search-bar {
  margin-bottom: var(--space-5);
}
.search-row {
  display: flex;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}
.filter-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}
.filter-item {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}
.filter-label {
  font-size: 13px;
  color: var(--c-text-2);
  white-space: nowrap;
}
.result-count {
  margin-left: auto;
  font-size: 12px;
  color: var(--c-text-3);
}

/* 主体区域 */
.jobs-main {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--space-5);
  position: relative;
}
.jobs-main:has(.job-detail-panel) {
  grid-template-columns: 1fr 380px;
}

/* 列表区域 */
.list-loading,
.list-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 300px;
  gap: var(--space-3);
  color: var(--c-text-3);
  font-size: 14px;
}

/* 岗位卡片 Grid */
.jobs-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-4);
}
.job-card {
  background: var(--c-surface);
  border-radius: var(--radius-md);
  padding: var(--space-4);
  border: 1px solid var(--c-bg-mute);
  box-shadow: var(--shadow-xs);
  cursor: pointer;
  transition: all var(--duration-fast) ease;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.job-card:hover {
  box-shadow: var(--shadow-md);
  border-color: var(--c-brand-lighter);
  transform: translateY(-1px);
}
.job-card.selected {
  border-color: var(--c-brand);
  background: var(--c-brand-lighter);
}

/* 卡片顶部 */
.card-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--space-2);
}
.job-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--c-text-1);
  margin: 0;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.job-tags {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

/* 信息行 */
.job-info-row {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.info-pill {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--c-text-2);
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  background: var(--c-bg-soft);
}
.info-pill .salary,
.info-pill:has(.salary) {
  color: #f59e0b;
}

/* 技能标签 */
.skill-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.skill-tag {
  font-size: 11px;
  padding: 1px 8px;
  border-radius: var(--radius-sm);
  background: rgba(99, 102, 241, 0.08);
  color: #6366f1;
}

/* 摘要 */
.job-summary {
  font-size: 12px;
  color: var(--c-text-3);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  margin: 0;
}

/* 卡片底部 */
.card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: var(--space-2);
  border-top: 1px solid var(--c-bg-mute);
}
.update-time {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--c-text-3);
}

/* 分页 */
.pagination {
  display: flex;
  justify-content: center;
  margin-top: var(--space-5);
}

/* 详情侧边栏 */
.job-detail-panel {
  background: var(--c-surface);
  border-radius: var(--radius-md);
  border: 1px solid var(--c-bg-mute);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
  position: sticky;
  top: 20px;
  align-self: start;
  max-height: calc(100vh - 120px);
  display: flex;
  flex-direction: column;
}
.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-4);
  border-bottom: 1px solid var(--c-bg-mute);
}
.detail-header h3 {
  font-size: 15px;
  font-weight: 600;
  color: var(--c-text-1);
  margin: 0;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.detail-body {
  overflow-y: auto;
  padding: var(--space-4);
  flex: 1;
}

/* 详情区块 */
.detail-section {
  margin-bottom: var(--space-4);
}
.detail-section:last-child {
  margin-bottom: 0;
}
.detail-tags {
  display: flex;
  gap: var(--space-1);
  flex-wrap: wrap;
}
.section-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--c-text-1);
  margin: 0 0 var(--space-2) 0;
}

/* 详情 Grid */
.detail-grid {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.detail-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-2) var(--space-3);
  background: var(--c-bg-soft);
  border-radius: var(--radius-sm);
}
.item-label {
  font-size: 12px;
  color: var(--c-text-3);
}
.item-value {
  font-size: 12px;
  color: var(--c-text-2);
  font-weight: 500;
}
.item-value.salary {
  color: #f59e0b;
}

/* 技能标签 */
.detail-skills {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.detail-skill-tag {
  font-size: 12px;
  padding: 2px 10px;
  border-radius: var(--radius-sm);
  background: rgba(99, 102, 241, 0.08);
  color: #6366f1;
  border: 1px solid rgba(99, 102, 241, 0.15);
}

/* 描述 */
.detail-summary {
  font-size: 13px;
  color: var(--c-text-2);
  line-height: 1.6;
  margin: 0;
}

/* 职业发展 */
.detail-career pre {
  font-size: 12px;
  color: var(--c-text-2);
  background: var(--c-bg-soft);
  padding: var(--space-3);
  border-radius: var(--radius-sm);
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
  max-height: 150px;
  overflow-y: auto;
}

/* 能力强度 */
.detail-intensity {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.intensity-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.intensity-label {
  width: 80px;
  font-size: 12px;
  color: var(--c-text-3);
  flex-shrink: 0;
}
.intensity-bar-bg {
  flex: 1;
  height: 6px;
  background: var(--c-bg-soft);
  border-radius: var(--radius-full);
  overflow: hidden;
}
.intensity-bar-fill {
  height: 100%;
  border-radius: var(--radius-full);
  background: var(--c-brand);
  transition: width 0.4s ease;
}

/* 底部 */
.detail-footer {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--c-text-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--c-bg-mute);
}

/* 过渡动画 */
.slide-fade-enter-active {
  transition: all 0.3s ease;
}
.slide-fade-leave-active {
  transition: all 0.2s ease;
}
.slide-fade-enter-from,
.slide-fade-leave-to {
  transform: translateX(20px);
  opacity: 0;
}

/* 响应式 */
@media (max-width: 768px) {
  .jobs-grid {
    grid-template-columns: 1fr;
  }
  .jobs-main:has(.job-detail-panel) {
    grid-template-columns: 1fr;
  }
  .job-detail-panel {
    position: relative;
    top: 0;
    max-height: none;
  }
}
</style>
