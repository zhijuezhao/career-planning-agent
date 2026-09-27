<script setup lang="ts">
/**
 * 岗位管理（P1-3 / B2-5，需求 2）
 *
 * 列：岗位名称 / **公司（主公司 + 在招公司数）** / 级别 / 行业 / 学历 / 薪资 / 经验 /
 *     **岗位画像（逐字段详情）** / 导入时间 / 最近更新
 * 画像：每个字段一个「详情」按钮 → `DetailDialog`（Markdown 预览 + JSON 页签）
 * 公司（B2-5）：岗位↔公司是多对多；「在招公司」弹窗列出全部在招该岗位的公司
 * 编辑：仅标量字段；JSONB 画像本轮只读预览（改画像需要结构化编辑器，留待后续）
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { get, post, put, remove } from '@/api/request'
import { DetailDialog } from '@/components'
import type { DetailTag } from '@/components'
import { formatDateTime, jobPortraitSections } from '@/utils/preview'
import type { PortraitSection } from '@/utils/preview'

interface JobItem {
  id: number
  title: string
  industry: string | null
  level: string | null
  salary_range: string | null
  education_requirement: string | null
  experience_requirement: string | null
  summary: string | null
  hard_skills: unknown
  soft_skills: unknown
  requirement_intensity: unknown
  career_path: unknown
  transition_paths: unknown
  outlook: unknown
  company_name: string | null
  company_count: number
  created_at: string
  updated_at: string
}

/** 一条在招关联 = **一次招聘**（任务 2 起岗位↔公司多对多；任务 4 接上招聘级字段） */
interface JobCompanyLink {
  company_id: number
  company_name: string
  industry: string | null
  scale: string | null
  region: string | null
  city: string | null
  salary: string | null
  source_url: string | null
  hit_count: number
  last_seen_at: string | null
  is_primary: boolean
}

/** 省 → 市级联下拉的数据源（选项是库里真实存在的值，可能是空的） */
interface GeoOptions {
  regions: string[]
  cities_by_region: Record<string, string[]>
  all_cities: string[]
}

interface CompanyOption {
  id: number
  name: string
  job_count: number
}

const route = useRoute()

const loading = ref(false)
const tableData = ref<JobItem[]>([])
const total = ref(0)
const dialogVisible = ref(false)
const submitting = ref(false)
const editingId = ref<number | null>(null)
const formRef = ref<FormInstance>()
const companies = ref<CompanyOption[]>([])

// B2-2：支持从「公司导航」跳过来时带上 company_id（?company_id=123）
const initialCompanyId = Number(route.query.company_id ?? 0) || undefined

const query = reactive({
  page: 1,
  limit: 20,
  industry: '',
  level: '',
  company_id: initialCompanyId as number | undefined,
  region: '',
  city: '',
})

// ── 省 → 市级联（任务 4）────────────────────────────────────────────────────
// 口径 = **招聘所在地**（关联行自带的地域优先，缺失回落公司所在地），与后端筛选、
// 与详情「在招公司」三处一致。选项来自 `GET /jobs/geo-options`；空库 → 空下拉。
const geoOptions = ref<GeoOptions>({ regions: [], cities_by_region: {}, all_cities: [] })

const cityOptions = computed(() =>
  query.region
    ? (geoOptions.value.cities_by_region[query.region] ?? [])
    : geoOptions.value.all_cities,
)

const loadGeoOptions = async () => {
  try {
    geoOptions.value = await get<GeoOptions>('/v1/admin/jobs/geo-options')
  } catch {
    // error handled by interceptor
  }
}

const handleRegionChange = () => {
  // 换了省之后，原来的市可能不属于新省 → 清掉，免得出现"空结果但筛选器看着有值"
  if (query.city && !cityOptions.value.includes(query.city)) query.city = ''
  handleSearch()
}

const form = reactive({
  title: '',
  industry: '',
  level: '',
  salary_range: '',
  education_requirement: '',
  experience_requirement: '',
  summary: '',
})

const rules: FormRules = {
  title: [{ required: true, message: '请输入岗位名称', trigger: 'blur' }],
}

const dialogTitle = computed(() => (editingId.value === null ? '新建岗位' : `编辑岗位 #${editingId.value}`))

const sectionsOf = (row: JobItem): PortraitSection[] => jobPortraitSections(row)

const fetchCompanies = async () => {
  try {
    const res = await get<{ items: CompanyOption[] }>('/v1/admin/companies', {
      params: { limit: 100, only_with_jobs: true, sort: 'job_count' },
    })
    companies.value = res.items
  } catch {
    // error handled by interceptor
  }
}

// ── 在招公司（B2-5）──────────────────────────────────────────────────────────

const linkVisible = ref(false)
const linkLoading = ref(false)
const linkTitle = ref('')
const linkRows = ref<JobCompanyLink[]>([])

const openCompanies = async (row: JobItem) => {
  linkTitle.value = `「${row.title}」在招公司`
  linkVisible.value = true
  linkLoading.value = true
  try {
    const detail = await get<{ companies: JobCompanyLink[] }>(`/v1/admin/jobs/${row.id}`)
    linkRows.value = detail.companies || []
  } catch {
    // error handled by interceptor
  } finally {
    linkLoading.value = false
  }
}

const fetchData = async () => {
  loading.value = true
  try {
    const params: Record<string, unknown> = {
      skip: (query.page - 1) * query.limit,
      limit: query.limit,
    }
    if (query.industry) params.industry = query.industry
    if (query.level) params.level = query.level
    if (query.company_id) params.company_id = query.company_id
    if (query.region) params.region = query.region
    if (query.city) params.city = query.city
    const res = await get<{ items: JobItem[]; total: number }>('/v1/admin/jobs', { params })
    tableData.value = res.items
    total.value = res.total
  } catch {
    // error handled by interceptor
  } finally {
    loading.value = false
  }
}

const handleSearch = () => {
  query.page = 1
  fetchData()
}

// ── 新建 / 编辑 ─────────────────────────────────────────────────────────────

const resetForm = () => {
  form.title = ''
  form.industry = ''
  form.level = ''
  form.salary_range = ''
  form.education_requirement = ''
  form.experience_requirement = ''
  form.summary = ''
}

const handleCreate = () => {
  editingId.value = null
  resetForm()
  dialogVisible.value = true
}

const handleEdit = (row: JobItem) => {
  editingId.value = row.id
  form.title = row.title
  form.industry = row.industry ?? ''
  form.level = row.level ?? ''
  form.salary_range = row.salary_range ?? ''
  form.education_requirement = row.education_requirement ?? ''
  form.experience_requirement = row.experience_requirement ?? ''
  form.summary = row.summary ?? ''
  dialogVisible.value = true
}

/** 空串转 null：避免把 "" 写进库（与后端 Optional 语义一致） */
const payload = () => ({
  title: form.title.trim(),
  industry: form.industry.trim() || null,
  level: form.level.trim() || null,
  salary_range: form.salary_range.trim() || null,
  education_requirement: form.education_requirement.trim() || null,
  experience_requirement: form.experience_requirement.trim() || null,
  summary: form.summary.trim() || null,
})

const handleSubmit = async () => {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    submitting.value = true
    try {
      if (editingId.value === null) {
        await post('/v1/admin/jobs', payload())
        ElMessage.success('创建成功')
      } else {
        await put(`/v1/admin/jobs/${editingId.value}`, payload())
        ElMessage.success('保存成功')
      }
      dialogVisible.value = false
      await fetchData()
    } catch {
      // error handled by interceptor
    } finally {
      submitting.value = false
    }
  })
}

// ── 操作 ────────────────────────────────────────────────────────────────────

const handleDelete = async (row: JobItem) => {
  try {
    await ElMessageBox.confirm(`确定删除岗位「${row.title}」？`, '提示', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await remove(`/v1/admin/jobs/${row.id}`)
    ElMessage.success('删除成功')
    await fetchData()
  } catch {
    // error handled by interceptor
  }
}

const handleReEmbed = async (row: JobItem) => {
  try {
    await post(`/v1/admin/jobs/${row.id}/re-embed`)
    ElMessage.success('向量已重算')
  } catch {
    // error handled by interceptor
  }
}

// ── 画像详情预览卡 ──────────────────────────────────────────────────────────

const detailVisible = ref(false)
const detailTitle = ref('')
const detailSubtitle = ref('')
const detailTags = ref<DetailTag[]>([])
const detailMarkdown = ref('')
const detailJson = ref<unknown>(undefined)

const openPortrait = (row: JobItem, section: PortraitSection) => {
  detailTitle.value = `岗位画像 · ${section.label}`
  detailSubtitle.value = `${row.title}（ID ${row.id}）`
  const tags: DetailTag[] = []
  if (row.industry) tags.push({ text: row.industry, type: 'info' })
  if (row.level) tags.push({ text: row.level, type: 'primary' })
  if (row.salary_range) tags.push({ text: row.salary_range, type: 'success' })
  detailTags.value = tags
  detailMarkdown.value = section.markdown
  detailJson.value = row[section.key]
  detailVisible.value = true
}

onMounted(async () => {
  await fetchCompanies()
  await loadGeoOptions()
  await fetchData()
})
</script>

<template>
  <div>
    <el-card class="data-card">
      <div class="toolbar">
        <el-select
          v-model="query.company_id"
          placeholder="全部公司"
          style="width: 220px"
          clearable
          filterable
          @change="handleSearch"
        >
          <el-option
            v-for="c in companies"
            :key="c.id"
            :label="`${c.name}（${c.job_count}）`"
            :value="c.id"
          />
        </el-select>
        <el-input v-model="query.industry" placeholder="行业" style="width: 150px" clearable />
        <el-input v-model="query.level" placeholder="级别" style="width: 150px" clearable />
        <!-- 省 → 市级联（任务 4，按招聘所在地；选中省后「市」的选项收敛到该省的市） -->
        <el-select
          v-model="query.region"
          placeholder="全部省份"
          style="width: 140px"
          clearable
          filterable
          @change="handleRegionChange"
        >
          <el-option v-for="r in geoOptions.regions" :key="r" :label="r" :value="r" />
        </el-select>
        <el-select
          v-model="query.city"
          placeholder="全部城市"
          style="width: 140px"
          clearable
          filterable
          @change="handleSearch"
        >
          <el-option v-for="c in cityOptions" :key="c" :label="c" :value="c" />
        </el-select>
        <el-button type="primary" @click="handleSearch">搜索</el-button>
        <el-button type="success" @click="handleCreate">新建</el-button>
      </div>

      <el-table v-loading="loading" :data="tableData" stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="title" label="岗位名称" min-width="160" show-overflow-tooltip />
        <el-table-column label="公司" width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="company-cell">
              <span>{{ row.company_name || '-' }}</span>
              <el-button
                v-if="row.company_count > 1"
                type="primary"
                size="small"
                link
                @click="openCompanies(row)"
              >
                等 {{ row.company_count }} 家
              </el-button>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="level" label="级别" width="80" />
        <el-table-column prop="industry" label="所属行业" width="120" show-overflow-tooltip />
        <el-table-column prop="education_requirement" label="学历要求" width="100" show-overflow-tooltip />
        <el-table-column prop="salary_range" label="薪资范围" width="120" show-overflow-tooltip />
        <el-table-column prop="experience_requirement" label="经验要求" width="120" show-overflow-tooltip />

        <el-table-column label="岗位画像" min-width="300">
          <template #default="{ row }">
            <div class="portrait-cell">
              <el-button
                v-for="section in sectionsOf(row)"
                :key="section.key"
                size="small"
                link
                type="primary"
                :disabled="section.empty"
                @click="openPortrait(row, section)"
              >
                {{ section.label }}
              </el-button>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="导入时间" width="170">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="最近更新" width="170">
          <template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template>
        </el-table-column>

        <el-table-column label="操作" width="210" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" size="small" link @click="handleEdit(row)">编辑</el-button>
            <el-button type="warning" size="small" link @click="handleReEmbed(row)">重算向量</el-button>
            <el-button type="danger" size="small" link @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="query.page"
        :page-size="query.limit"
        :total="total"
        layout="total, prev, pager, next"
        @current-change="fetchData"
      />
    </el-card>

    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="600px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="岗位名称" prop="title">
          <el-input v-model="form.title" />
        </el-form-item>
        <el-form-item label="所属行业">
          <el-input v-model="form.industry" />
        </el-form-item>
        <el-form-item label="级别">
          <el-select v-model="form.level" placeholder="请选择" clearable style="width: 100%">
            <el-option label="初级" value="初级" />
            <el-option label="中级" value="中级" />
            <el-option label="高级" value="高级" />
          </el-select>
        </el-form-item>
        <el-form-item label="薪资范围">
          <el-input v-model="form.salary_range" placeholder="如 15000-25000 或 15K-25K" />
        </el-form-item>
        <el-form-item label="学历要求">
          <el-input v-model="form.education_requirement" placeholder="如 本科及以上" />
        </el-form-item>
        <el-form-item label="经验要求">
          <el-input v-model="form.experience_requirement" placeholder="如 3-5年" />
        </el-form-item>
        <el-form-item label="画像摘要">
          <el-input v-model="form.summary" type="textarea" :rows="4" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>

    <DetailDialog
      v-model="detailVisible"
      :title="detailTitle"
      :subtitle="detailSubtitle"
      :tags="detailTags"
      :markdown="detailMarkdown"
      :json="detailJson"
      width="800px"
    />

    <el-dialog v-model="linkVisible" :title="linkTitle" width="880px">
      <el-table v-loading="linkLoading" :data="linkRows" size="small" stripe>
        <el-table-column label="公司" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.company_name }}
            <el-tag v-if="row.is_primary" size="small" type="success" class="primary-tag">最早</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="行业" width="110">
          <template #default="{ row }">{{ row.industry || '-' }}</template>
        </el-table-column>
        <el-table-column label="规模" width="120">
          <template #default="{ row }">{{ row.scale || '-' }}</template>
        </el-table-column>
        <el-table-column label="省份" width="90">
          <template #default="{ row }">{{ row.region || '-' }}</template>
        </el-table-column>
        <el-table-column label="城市" width="90">
          <template #default="{ row }">{{ row.city || '-' }}</template>
        </el-table-column>
        <el-table-column label="薪资" width="110">
          <template #default="{ row }">{{ row.salary || '-' }}</template>
        </el-table-column>
        <el-table-column label="招聘链接" width="110">
          <template #default="{ row }">
            <el-link
              v-if="row.source_url"
              type="primary"
              :href="row.source_url"
              target="_blank"
              rel="noopener"
            >
              打开
            </el-link>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="出现次数" width="90">
          <template #default="{ row }">{{ row.hit_count }}</template>
        </el-table-column>
        <el-table-column label="最近一次" width="170">
          <template #default="{ row }">{{ formatDateTime(row.last_seen_at) }}</template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!linkLoading && linkRows.length === 0" description="暂无在招公司" :image-size="60" />
      <template #footer>
        <el-button type="primary" @click="linkVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.data-card {
  border-radius: 12px;
  border: 1px solid #e6e6e6;
}

.toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.portrait-cell {
  display: flex;
  flex-wrap: wrap;
  gap: 2px 8px;
}

.company-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}

.primary-tag {
  margin-left: 6px;
}
</style>
