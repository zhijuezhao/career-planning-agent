<script setup lang="ts">
/**
 * 快照管理（P1-4，需求 5）
 *
 * 列：快照ID / 用户ID / 用户名 / 生成时间 / 匹配状态 / 六维摘要 / 详情 / 操作（下载·修改·删除）
 * - 详情：按需拉 `/snapshots/{id}`，用 `DetailDialog` 展示五层画像 Markdown + JSON
 * - 下载：后端渲染 Markdown（含六维分数表与原始表单附录），axios blob + 临时 <a>
 * - 修改：备注 + 五层画像 JSON（前端先校验 JSON；**不重算向量**，界面明示）
 * - 删除：**会连带删除该快照下的报告记录**（DB 级联），确认框里用 report_count 明示
 */
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { get, put, remove } from '@/api/request'
import { DetailDialog } from '@/components'
import type { DetailTag } from '@/components'
import { formatDateTime, snapshotMarkdown } from '@/utils/preview'

interface SnapshotItem {
  id: number
  user_id: number
  username: string | null
  profile_id: number
  serial_no: string
  description: string
  matched: boolean
  matched_at: string | null
  created_at: string
  six_dim_scores: Record<string, number>
  report_count: number
}

interface SnapshotDetail extends SnapshotItem {
  five_layers: Record<string, unknown>
  form_raw: Record<string, unknown>
  embedding_dim: number | null
}

const loading = ref(false)
const tableData = ref<SnapshotItem[]>([])
const total = ref(0)

const query = reactive({
  page: 1,
  limit: 20,
  user_id: undefined as number | undefined,
  matched: '' as '' | 'true' | 'false',
})

const dimSummary = (scores: Record<string, number> | undefined) =>
  Object.entries(scores ?? {})
    .map(([key, value]) => `${key} ${Number(value).toFixed(1)}`)
    .join(' · ')

const fetchData = async () => {
  loading.value = true
  try {
    const params: Record<string, unknown> = {
      skip: (query.page - 1) * query.limit,
      limit: query.limit,
    }
    if (query.user_id) params.user_id = query.user_id
    if (query.matched !== '') params.matched = query.matched
    const res = await get<{ items: SnapshotItem[]; total: number }>(
      '/v1/admin/matching/snapshots',
      { params },
    )
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

// ── 详情预览卡 ──────────────────────────────────────────────────────────────

const detailVisible = ref(false)
const detailLoading = ref(false)
const detailTitle = ref('')
const detailSubtitle = ref('')
const detailTags = ref<DetailTag[]>([])
const detailMarkdown = ref('')
const detailJson = ref<unknown>(undefined)

const openDetail = async (row: SnapshotItem) => {
  detailLoading.value = true
  try {
    const detail = await get<SnapshotDetail>(`/v1/admin/matching/snapshots/${row.id}`)
    detailTitle.value = '画像快照详情'
    detailSubtitle.value = `快照 #${detail.id} · ${detail.serial_no}`
    const tags: DetailTag[] = [
      { text: detail.matched ? '已匹配' : '待匹配', type: detail.matched ? 'success' : 'info' },
      { text: `用户 ${detail.username ?? detail.user_id}`, type: 'primary' },
    ]
    if (detail.embedding_dim) tags.push({ text: `向量 ${detail.embedding_dim} 维`, type: 'info' })
    if (detail.report_count > 0) tags.push({ text: `报告 ${detail.report_count} 份`, type: 'warning' })
    detailTags.value = tags
    detailMarkdown.value = snapshotMarkdown({
      ...detail,
      five_layers: detail.five_layers,
      six_dim_scores: detail.six_dim_scores,
    })
    detailJson.value = {
      five_layers: detail.five_layers,
      six_dim_scores: detail.six_dim_scores,
      form_raw: detail.form_raw,
      embedding_dim: detail.embedding_dim,
    }
    detailVisible.value = true
  } catch {
    // error handled by interceptor
  } finally {
    detailLoading.value = false
  }
}

// ── 修改（备注 + 五层画像）──────────────────────────────────────────────────

const editVisible = ref(false)
const editSaving = ref(false)
const editTargetId = ref<number | null>(null)
const jsonError = ref('')
const editForm = reactive({
  description: '',
  fiveLayersText: '',
})

const openEdit = async (row: SnapshotItem) => {
  try {
    const detail = await get<SnapshotDetail>(`/v1/admin/matching/snapshots/${row.id}`)
    editTargetId.value = row.id
    editForm.description = detail.description ?? ''
    editForm.fiveLayersText = JSON.stringify(detail.five_layers ?? {}, null, 2)
    jsonError.value = ''
    editVisible.value = true
  } catch {
    // error handled by interceptor
  }
}

const submitEdit = async () => {
  if (editTargetId.value === null) return

  let parsed: unknown
  try {
    parsed = JSON.parse(editForm.fiveLayersText || '{}')
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error('最外层必须是 JSON 对象')
    }
  } catch (error) {
    jsonError.value = `五层画像 JSON 解析失败：${(error as Error).message}`
    return
  }
  jsonError.value = ''

  editSaving.value = true
  try {
    await put(`/v1/admin/matching/snapshots/${editTargetId.value}`, {
      description: editForm.description,
      five_layers: parsed,
    })
    ElMessage.success('已保存（向量未重算）')
    editVisible.value = false
    await fetchData()
  } catch {
    // error handled by interceptor
  } finally {
    editSaving.value = false
  }
}

// ── 下载 / 删除 ─────────────────────────────────────────────────────────────

const handleDownload = async (row: SnapshotItem) => {
  try {
    const blob = await get<Blob>(`/v1/admin/matching/snapshots/${row.id}/download`, {
      responseType: 'blob',
    })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `快照_${row.user_id}_${row.serial_no}.md`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  } catch {
    // error handled by interceptor
  }
}

const handleDelete = async (row: SnapshotItem) => {
  const warning =
    row.report_count > 0
      ? `该快照下有 ${row.report_count} 份报告记录，会一并被删除（Word 文件尽力清理）。`
      : ''
  try {
    await ElMessageBox.confirm(`确定删除快照 #${row.id}？${warning}`, '删除确认', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await remove(`/v1/admin/matching/snapshots/${row.id}`)
    ElMessage.success('删除成功')
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
      <div class="toolbar">
        <el-input
          v-model.number="query.user_id"
          placeholder="用户ID"
          style="width: 140px"
          clearable
        />
        <el-select v-model="query.matched" placeholder="匹配状态" style="width: 140px">
          <el-option label="全部" value="" />
          <el-option label="已匹配" value="true" />
          <el-option label="待匹配" value="false" />
        </el-select>
        <el-button type="primary" @click="handleSearch">搜索</el-button>
        <el-button @click="fetchData">刷新</el-button>
      </div>

      <el-table v-loading="loading" :data="tableData" stripe>
        <el-table-column prop="id" label="快照ID" width="90" />
        <el-table-column prop="user_id" label="用户ID" width="90" />
        <el-table-column label="用户名" width="130" show-overflow-tooltip>
          <template #default="{ row }">{{ row.username ?? '-' }}</template>
        </el-table-column>
        <el-table-column label="生成时间" width="170">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="匹配状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.matched ? 'success' : 'info'" size="small">
              {{ row.matched ? '已匹配' : '待匹配' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="六维摘要" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">{{ dimSummary(row.six_dim_scores) || '-' }}</template>
        </el-table-column>
        <el-table-column label="详情" width="90">
          <template #default="{ row }">
            <el-button type="primary" size="small" link :loading="detailLoading" @click="openDetail(row)">
              查看
            </el-button>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="190" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" size="small" link @click="handleDownload(row)">下载</el-button>
            <el-button type="warning" size="small" link @click="openEdit(row)">修改</el-button>
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

    <DetailDialog
      v-model="detailVisible"
      :title="detailTitle"
      :subtitle="detailSubtitle"
      :tags="detailTags"
      :markdown="detailMarkdown"
      :json="detailJson"
      width="900px"
      empty-text="（该快照没有五层画像数据）"
    />

    <el-dialog v-model="editVisible" title="修改快照" width="720px">
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="修改五层画像不会重算向量与六维分数"
        description="向量仍是快照生成时那份；如需一致，请在学生端重新生成快照。"
        class="edit-alert"
      />
      <el-form label-width="90px">
        <el-form-item label="备注">
          <el-input v-model="editForm.description" maxlength="255" show-word-limit />
        </el-form-item>
        <el-form-item label="五层画像">
          <el-input
            v-model="editForm.fiveLayersText"
            type="textarea"
            :rows="14"
            spellcheck="false"
            class="json-editor"
          />
          <div v-if="jsonError" class="json-error">{{ jsonError }}</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="editSaving" @click="submitEdit">保存</el-button>
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

.edit-alert {
  margin-bottom: 12px;
}

.json-editor :deep(textarea) {
  font-family: 'JetBrains Mono', Consolas, Monaco, monospace;
  font-size: 12px;
  line-height: 1.6;
}

.json-error {
  margin-top: 6px;
  font-size: 12px;
  color: #f56c6c;
}
</style>
