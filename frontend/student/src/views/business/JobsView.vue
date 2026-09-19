<script setup lang="ts">
/**
 * 业务区 - 岗位库（Task 14）
 * 数据源：GET /jobs（分页 + 行业/层级/关键词筛选）、GET /jobs/{id}（详情抽屉）
 * 说明：岗位内容由管理端提供；当岗位尚未填写要求/描述时，页面按空值降级展示。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Briefcase, Refresh, Search, WarningFilled } from '@element-plus/icons-vue'
import EmptyState from '@/components/EmptyState.vue'
import { jobsApi, type JobProfileResponse } from '@/api/jobs'
import { useJourneyStore } from '@/stores/journey'

const PAGE_SIZE = 10

const router = useRouter()
const journey = useJourneyStore()

const loading = ref(true)
const error = ref('')
const items = ref<JobProfileResponse[]>([])
const total = ref(0)
const page = ref(1)
const keyword = ref('')
const industry = ref('')
const level = ref('')

const drawerVisible = ref(false)
const detail = ref<JobProfileResponse | null>(null)
const detailLoading = ref(false)

/** 行业下拉选项从当前页数据聚合（后端暂无独立的行业列表端点） */
const industryOptions = computed(() => {
  const set = new Set<string>()
  items.value.forEach(j => { if (j.industry) set.add(j.industry) })
  return Array.from(set)
})

function formatScalar(value: unknown): string {
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return ''
}

/** JSONB 字段（如 hard_skills）形态不可知 → 递归格式化 */
function formatValue(value: unknown): string {
  if (value == null) return ''
  const scalar = formatScalar(value)
  if (scalar) return scalar
  if (Array.isArray(value)) {
    return value.map(v => formatValue(v)).filter(Boolean).join('、')
  }
  if (typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>)
      .map(([k, v]) => {
        const text = formatValue(v)
        return text ? `${k}：${text}` : ''
      })
      .filter(Boolean)
      .join('；')
  }
  return ''
}

function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

async function loadJobs(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const res = await jobsApi.getList({
      skip: (page.value - 1) * PAGE_SIZE,
      limit: PAGE_SIZE,
      keyword: keyword.value.trim() || undefined,
      industry: industry.value || undefined,
      level: level.value || undefined,
    })
    items.value = res.items ?? []
    total.value = res.total ?? 0
  } catch {
    items.value = []
    total.value = 0
    error.value = '岗位列表加载失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

onMounted(() => { void loadJobs() })

function search(): void {
  page.value = 1
  void loadJobs()
}

function resetFilters(): void {
  keyword.value = ''
  industry.value = ''
  level.value = ''
  page.value = 1
  void loadJobs()
}

function onPageChange(next: number): void {
  page.value = next
  void loadJobs()
}

async function openDetail(job: JobProfileResponse): Promise<void> {
  drawerVisible.value = true
  detailLoading.value = true
  detail.value = job   // 先用列表数据渲染，避免抽屉瞬间空白
  try {
    detail.value = await jobsApi.getDetail(job.id)
  } catch {
    /* 详情失败保留列表数据 */
  } finally {
    detailLoading.value = false
  }
}

function goMatch(): void {
  drawerVisible.value = false
  journey.setGuideStep('resume')
  router.push('/guide/match')
}
</script>

<template>
  <div class="jobs-page">
    <header class="page-head">
      <div>
        <h2 class="page-title">岗位库</h2>
        <p class="page-desc">共 {{ total }} 个岗位；点击任意行查看详情。</p>
      </div>
      <el-button class="hover-lift" :icon="Briefcase" @click="goMatch">去匹配岗位</el-button>
    </header>

    <div class="filter-bar">
      <el-input
        v-model="keyword"
        class="filter-input"
        placeholder="按岗位名称搜索"
        clearable
        :prefix-icon="Search"
        @keyup.enter="search"
      />
      <el-select v-model="industry" class="filter-select" placeholder="全部行业" clearable>
        <el-option v-for="opt in industryOptions" :key="opt" :label="opt" :value="opt" />
      </el-select>
      <el-select v-model="level" class="filter-select" placeholder="全部层级" clearable>
        <el-option label="初级" value="初级" />
        <el-option label="中级" value="中级" />
        <el-option label="高级" value="高级" />
      </el-select>
      <el-button type="primary" class="hover-lift press-effect" @click="search">查询</el-button>
      <el-button class="hover-lift" @click="resetFilters">重置</el-button>
    </div>

    <div v-if="loading" class="state-box">
      <el-icon class="is-loading" :size="24"><Refresh /></el-icon>
      <p class="state-text">正在加载岗位…</p>
    </div>

    <p v-else-if="error" class="error-note">
      <el-icon><WarningFilled /></el-icon>
      <span>{{ error }}</span>
    </p>

    <EmptyState
      v-else-if="!items.length"
      :icon="Search"
      title="没有匹配的岗位"
      description="换个关键词或重置筛选条件试试；若岗位库为空，需由管理端导入岗位数据。"
      show-action
      action-text="重置筛选"
      @action="resetFilters"
    />

    <template v-else>
      <el-table :data="items" class="job-table" row-key="id" @row-click="openDetail">
        <el-table-column label="岗位名称" min-width="180">
          <template #default="{ row }">
            <span class="job-title">{{ row.title || '未命名岗位' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="行业" width="120">
          <template #default="{ row }">{{ row.industry || '—' }}</template>
        </el-table-column>
        <el-table-column label="层级" width="90">
          <template #default="{ row }">{{ row.level || '—' }}</template>
        </el-table-column>
        <el-table-column label="薪资范围" width="140">
          <template #default="{ row }">{{ row.salary_range || '—' }}</template>
        </el-table-column>
        <el-table-column label="学历要求" width="110">
          <template #default="{ row }">{{ row.education_requirement || '—' }}</template>
        </el-table-column>
        <el-table-column label="更新" width="110">
          <template #default="{ row }">{{ formatDate(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="openDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination
          layout="prev, pager, next, total"
          :total="total"
          :page-size="PAGE_SIZE"
          :current-page="page"
          @current-change="onPageChange"
        />
      </div>
    </template>

    <el-drawer v-model="drawerVisible" title="岗位详情" size="480px">
      <div v-if="detail" class="detail-body">
        <h3 class="detail-title">{{ detail.title || '未命名岗位' }}</h3>
        <div class="detail-tags">
          <span v-if="detail.industry" class="tag">{{ detail.industry }}</span>
          <span v-if="detail.level" class="tag">{{ detail.level }}</span>
          <span v-if="detail.salary_range" class="tag tag-brand">{{ detail.salary_range }}</span>
        </div>
        <p v-if="detailLoading" class="detail-loading">正在加载完整详情…</p>

        <dl class="detail-list">
          <template v-if="detail.education_requirement">
            <dt>学历要求</dt><dd>{{ detail.education_requirement }}</dd>
          </template>
          <template v-if="detail.experience_requirement">
            <dt>经验要求</dt><dd>{{ detail.experience_requirement }}</dd>
          </template>
          <template v-if="formatValue(detail.hard_skills)">
            <dt>硬技能要求</dt><dd>{{ formatValue(detail.hard_skills) }}</dd>
          </template>
          <template v-if="formatValue(detail.soft_skills)">
            <dt>软技能要求</dt><dd>{{ formatValue(detail.soft_skills) }}</dd>
          </template>
          <template v-if="detail.summary">
            <dt>岗位描述</dt><dd>{{ detail.summary }}</dd>
          </template>
        </dl>
        <p
          v-if="!detail.education_requirement && !detail.experience_requirement
            && !formatValue(detail.hard_skills) && !formatValue(detail.soft_skills) && !detail.summary"
          class="detail-empty"
        >
          该岗位尚未填写详细要求与描述（由管理端维护）。
        </p>

        <div class="detail-actions">
          <el-button type="primary" class="hover-lift press-effect" @click="goMatch">去匹配岗位</el-button>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.jobs-page {
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
.filter-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--c-surface);
  border: 1px solid var(--c-bg-mute);
  border-radius: var(--radius-md);
}
.filter-input {
  width: 240px;
}
.filter-select {
  width: 150px;
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
.job-table {
  background: var(--c-surface);
  border-radius: var(--radius-md);
}
.job-title {
  font-weight: 500;
  color: var(--c-text-1);
}
.pager {
  display: flex;
  justify-content: flex-end;
}

/* 详情抽屉 */
.detail-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.detail-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--c-text-1);
}
.detail-tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
.tag {
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-full);
  background: var(--c-bg-soft);
  color: var(--c-text-2);
  font-size: var(--text-xs);
}
.tag-brand {
  background: var(--c-brand-lighter);
  color: var(--c-brand);
}
.detail-loading {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--c-text-3);
}
.detail-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin: 0;
}
.detail-list dt {
  font-size: var(--text-xs);
  color: var(--c-text-3);
}
.detail-list dd {
  margin: 0 0 var(--space-2);
  font-size: var(--text-sm);
  line-height: 1.7;
  color: var(--c-text-2);
  word-break: break-word;
}
.detail-empty {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--c-text-3);
}
.detail-actions {
  display: flex;
  gap: var(--space-3);
}

@media (max-width: 768px) {
  .filter-input,
  .filter-select {
    width: 100%;
  }
}
</style>
