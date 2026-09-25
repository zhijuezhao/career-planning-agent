<script setup lang="ts">
/**
 * 公司导航（B2-2，需求 3）
 *
 * 公司不是手工维护的：导入/落库时按「公司名」幂等 upsert，`job_count` 由后端按
 * `job_profiles.company_id` 实算。本页只做导航 + 人工修正：
 * - 列表：按岗位数倒序（先看到主要雇主），支持名称搜索 / 行业 / 城市 / 只看有岗位
 * - 详情：公司信息 + 该公司岗位（可直接跳到「岗位管理」按公司筛选）
 * - 修正：改公司名/行业/城市；「重算岗位数」对应 POST /companies/sync
 * - 删除：只删公司行，**岗位不受影响**（外键 ON DELETE SET NULL，只解绑）
 */
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { get, post, put, remove } from '@/api/request'
import { formatDateTime } from '@/utils/preview'

interface Company {
  id: number
  name: string
  industry: string | null
  city: string | null
  job_count: number
  created_at: string
  updated_at: string
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
  city: '',
  only_with_jobs: false,
  sort: 'job_count' as 'job_count' | 'name' | 'created_at',
})

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
const editForm = reactive({ name: '', industry: '', city: '' })

const openEdit = (row: Company) => {
  editingId.value = row.id
  editForm.name = row.name
  editForm.industry = row.industry ?? ''
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
      city: editForm.city || null,
    })
    ElMessage.success('已保存')
    editVisible.value = false
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

onMounted(fetchData)
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
        <el-input v-model="query.city" placeholder="城市" style="width: 120px" clearable />
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
        <el-form-item label="城市">
          <el-input v-model="editForm.city" placeholder="如：北京" maxlength="50" />
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
