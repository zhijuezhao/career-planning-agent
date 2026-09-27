<script setup lang="ts">
/**
 * 公司导航（B2-2，需求 3）
 *
 * 公司不是手工维护的：导入/落库时按「公司名」幂等 upsert，`job_count` 由后端按
 * `job_company_links` 实算（任务 3 起 `job_profiles.company_id` 已删除）。
 * 本页只做导航 + 人工修正：
 * - 列表：按岗位数倒序（先看到主要雇主），支持名称搜索 / 行业 / **省→市级联** / 只看有岗位
 * - 详情：公司信息 + 该公司岗位（可直接跳到「岗位管理」按公司筛选）
 * - 修正：改公司名/行业/**规模/省/市**；「重算岗位数」对应 POST /companies/sync
 * - 删除：只删公司行，**岗位不受影响**（关联行随公司级联删除，岗位本身保留）
 *
 * 任务 4（2026-09-27）：规模与省/市是新增字段；地域用**省→市级联下拉**，
 * 选项来自 `GET /companies/geo-options`（库里真实存在的 distinct 值）。
 * 空库时那三个列表都是空的 → 下拉空着显示，**不硬编码任何省份表**。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { get, post, put, remove } from '@/api/request'
import { formatDateTime } from '@/utils/preview'

interface Company {
  id: number
  name: string
  industry: string | null
  scale: string | null
  region: string | null
  city: string | null
  job_count: number
  created_at: string
  updated_at: string
}

/** 省 → 市级联下拉的数据源（选项是库里真实存在的值，可能是空的） */
interface GeoOptions {
  regions: string[]
  cities_by_region: Record<string, string[]>
  all_cities: string[]
}

interface CompanyJob {
  id: number
  title: string
  industry: string | null
  level: string | null
  salary_range: string | null
  created_at: string
}

interface CompanyDetail extends Company {
  jobs: CompanyJob[]
}

const router = useRouter()

const loading = ref(false)
const rows = ref<Company[]>([])
const total = ref(0)
const syncing = ref(false)

const query = reactive({
  page: 1,
  limit: 20,
  q: '',
  industry: '',
  region: '',
  city: '',
  only_with_jobs: false,
  sort: 'job_count' as 'job_count' | 'name' | 'created_at',
})

// ── 省 → 市级联（任务 4）────────────────────────────────────────────────────
// 选项来自后端 distinct 值；未选省时「市」给全部市（含"只写了市没写省"的行，
// 否则那些公司在当前筛选器里永远筛不到）。
const geoOptions = ref<GeoOptions>({ regions: [], cities_by_region: {}, all_cities: [] })

const cityOptions = computed(() =>
  query.region
    ? (geoOptions.value.cities_by_region[query.region] ?? [])
    : geoOptions.value.all_cities,
)

const loadGeoOptions = async () => {
  try {
    geoOptions.value = await get<GeoOptions>('/v1/admin/companies/geo-options')
  } catch {
    // error handled by interceptor
  }
}

const handleRegionChange = () => {
  // 换了省之后，原来的市可能不属于新省 → 清掉，免得出现"空结果但筛选器看着有值"
  if (query.city && !cityOptions.value.includes(query.city)) query.city = ''
  handleSearch()
}

const fetchData = async () => {
  loading.value = true
  try {
    const params: Record<string, unknown> = {
      skip: (query.page - 1) * query.limit,
      limit: query.limit,
      sort: query.sort,
    }
    if (query.q) params.q = query.q
    if (query.industry) params.industry = query.industry
    if (query.region) params.region = query.region
    if (query.city) params.city = query.city
    if (query.only_with_jobs) params.only_with_jobs = true

    const res = await get<{ items: Company[]; total: number }>('/v1/admin/companies', { params })
    rows.value = res.items
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

// ── 详情 ────────────────────────────────────────────────────────────────────

const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<CompanyDetail | null>(null)

const openDetail = async (row: Company) => {
  detailLoading.value = true
  detailVisible.value = true
  try {
    detail.value = await get<CompanyDetail>(`/v1/admin/companies/${row.id}`)
  } catch {
    // error handled by interceptor
  } finally {
    detailLoading.value = false
  }
}

const goJobs = (companyId: number) => {
  router.push({ path: '/jobs', query: { company_id: String(companyId) } })
}

// ── 编辑 ────────────────────────────────────────────────────────────────────

const editVisible = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)
const editForm = reactive({ name: '', industry: '', scale: '', region: '', city: '' })

const openEdit = (row: Company) => {
  editingId.value = row.id
  editForm.name = row.name
  editForm.industry = row.industry ?? ''
  editForm.scale = row.scale ?? ''
  editForm.region = row.region ?? ''
  editForm.city = row.city ?? ''
  editVisible.value = true
}

const submitEdit = async () => {
  if (editingId.value === null) return
  saving.value = true
  try {
    await put(`/v1/admin/companies/${editingId.value}`, {
      name: editForm.name,
      industry: editForm.industry || null,
      scale: editForm.scale || null,
      region: editForm.region || null,
      city: editForm.city || null,
    })
    ElMessage.success('已保存')
    editVisible.value = false
    // 省/市/规模可能变了 → 级联选项跟着更新
    await loadGeoOptions()
    await fetchData()
  } catch {
    // error handled by interceptor
  } finally {
    saving.value = false
  }
}

// ── 重算 / 删除 ─────────────────────────────────────────────────────────────

const handleSync = async () => {
  syncing.value = true
  try {
    const res = await post<{ synced: number; with_jobs: number }>('/v1/admin/companies/sync')
    ElMessage.success(`已重算 ${res.synced} 家公司（其中有岗位 ${res.with_jobs} 家）`)
    await fetchData()
  } catch {
    // error handled by interceptor
  } finally {
    syncing.value = false
  }
}

const handleDelete = async (row: Company) => {
  try {
    await ElMessageBox.confirm(
      `删除公司「${row.name}」？其 ${row.job_count} 个岗位**不会被删除**，只会解除公司关联。`,
      '删除确认',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  try {
    await remove(`/v1/admin/companies/${row.id}`)
    ElMessage.success('已删除（岗位已解绑）')
    await fetchData()
  } catch {
    // error handled by interceptor
  }
}

onMounted(async () => {
  await loadGeoOptions()
  await fetchData()
})
</script>

<template>
  <div>
    <el-card class="data-card">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="公司由导入自动识别，不需要手工新建"
        description="岗位落库时按公司名幂等 upsert；这里只做导航与人工修正。删除公司不会删岗位（只解绑）。"
        class="hint"
      />

      <div class="toolbar">
        <el-input
          v-model="query.q"
          placeholder="公司名关键字"
          style="width: 220px"
          clearable
          @keyup.enter="handleSearch"
        />
        <el-input v-model="query.industry" placeholder="行业" style="width: 140px" clearable />
        <!-- 省 → 市级联（任务 4）：选中省后「市」的选项收敛到该省的市 -->
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
        <el-checkbox v-model="query.only_with_jobs" @change="handleSearch">只看有岗位</el-checkbox>
        <el-select v-model="query.sort" style="width: 150px" @change="handleSearch">
          <el-option label="按岗位数" value="job_count" />
          <el-option label="按名称" value="name" />
          <el-option label="按创建时间" value="created_at" />
        </el-select>
        <el-button type="primary" @click="handleSearch">搜索</el-button>
        <el-button :loading="syncing" @click="handleSync">重算岗位数</el-button>
      </div>

      <el-table v-loading="loading" :data="rows" stripe>
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="name" label="公司名" min-width="240" show-overflow-tooltip />
        <el-table-column label="行业" width="140">
          <template #default="{ row }">{{ row.industry || '-' }}</template>
        </el-table-column>
        <el-table-column label="规模" width="130">
          <template #default="{ row }">{{ row.scale || '-' }}</template>
        </el-table-column>
        <el-table-column label="省份" width="100">
          <template #default="{ row }">{{ row.region || '-' }}</template>
        </el-table-column>
        <el-table-column label="城市" width="110">
          <template #default="{ row }">{{ row.city || '-' }}</template>
        </el-table-column>
        <el-table-column label="岗位数" width="110">
          <template #default="{ row }">
            <el-tag :type="row.job_count > 0 ? 'success' : 'info'" size="small">
              {{ row.job_count }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最近更新" width="170">
          <template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" size="small" link @click="openDetail(row)">详情</el-button>
            <el-button type="success" size="small" link @click="goJobs(row.id)">岗位</el-button>
            <el-button type="warning" size="small" link @click="openEdit(row)">修正</el-button>
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

    <el-drawer v-model="detailVisible" title="公司详情" size="640px">
      <div v-loading="detailLoading">
        <el-descriptions v-if="detail" :column="1" border size="small">
          <el-descriptions-item label="公司名">{{ detail.name }}</el-descriptions-item>
          <el-descriptions-item label="行业">{{ detail.industry || '-' }}</el-descriptions-item>
          <el-descriptions-item label="规模">{{ detail.scale || '-' }}</el-descriptions-item>
          <el-descriptions-item label="省份">{{ detail.region || '-' }}</el-descriptions-item>
          <el-descriptions-item label="城市">{{ detail.city || '-' }}</el-descriptions-item>
          <el-descriptions-item label="岗位数">{{ detail.job_count }}</el-descriptions-item>
          <el-descriptions-item label="首次入库">
            {{ formatDateTime(detail.created_at) }}
          </el-descriptions-item>
        </el-descriptions>

        <div v-if="detail" class="drawer-actions">
          <el-button type="primary" size="small" @click="goJobs(detail.id)">
            在岗位管理里查看全部
          </el-button>
        </div>

        <el-divider content-position="left">该公司岗位（最近 {{ detail?.jobs.length ?? 0 }} 条）</el-divider>
        <el-table v-if="detail" :data="detail.jobs" size="small" stripe>
          <el-table-column prop="title" label="岗位" min-width="180" show-overflow-tooltip />
          <el-table-column label="行业" width="120">
            <template #default="{ row }">{{ row.industry || '-' }}</template>
          </el-table-column>
          <el-table-column label="薪资" width="120">
            <template #default="{ row }">{{ row.salary_range || '-' }}</template>
          </el-table-column>
        </el-table>
        <el-empty v-if="detail && detail.jobs.length === 0" description="该公司暂无关联岗位" :image-size="60" />
      </div>
    </el-drawer>

    <el-dialog v-model="editVisible" title="修正公司信息" width="520px">
      <el-form label-width="80px">
        <el-form-item label="公司名">
          <el-input v-model="editForm.name" maxlength="200" />
        </el-form-item>
        <el-form-item label="行业">
          <el-input v-model="editForm.industry" placeholder="如：互联网" maxlength="100" />
        </el-form-item>
        <el-form-item label="规模">
          <el-input v-model="editForm.scale" placeholder="如：1000-9999人" maxlength="50" />
        </el-form-item>
        <el-form-item label="省份">
          <el-input v-model="editForm.region" placeholder="如：广东（不带「省」后缀）" maxlength="50" />
        </el-form-item>
        <el-form-item label="城市">
          <el-input v-model="editForm.city" placeholder="如：深圳" maxlength="50" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.data-card {
  border-radius: 12px;
  border: 1px solid #e6e6e6;
}

.hint {
  margin-bottom: 14px;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.drawer-actions {
  margin: 14px 0;
}
</style>
