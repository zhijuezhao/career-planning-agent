<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { get, put, remove } from '@/api/request'

interface UserItem {
  id: number
  username: string
  email: string | null
  phone: string | null
  qq: string | null
  wechat: string | null
  role: string
  status: number
  created_at: string
}

/** 关联数据计数：删除前如实告知会连带删掉什么（来自 /users/{id}/stats） */
interface UserStats {
  resume_count: number
  match_count: number
  report_count: number
  chat_session_count: number
  snapshot_count: number
  profile_count: number
}

/** 角色白名单：与后端 backend/app/core/roles.py 的 UserRole 保持一致 */
const ROLE_OPTIONS = [
  { label: '学生', value: 'student' },
  { label: '管理员', value: 'admin' },
]
const roleLabel = (role: string) => ROLE_OPTIONS.find((o) => o.value === role)?.label ?? role

const loading = ref(false)
const tableData = ref<UserItem[]>([])
const total = ref(0)

const query = reactive({
  page: 1,
  limit: 20,
  keyword: '',
  role: '',
  status: undefined as number | undefined,
})

const fetchData = async () => {
  loading.value = true
  try {
    const params: Record<string, any> = {
      skip: (query.page - 1) * query.limit,
      limit: query.limit,
    }
    if (query.keyword) params.keyword = query.keyword
    if (query.role) params.role = query.role
    if (query.status !== undefined) params.status = query.status
    const res = await get<{ items: UserItem[]; total: number }>('/v1/admin/users', { params })
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

const handleReset = () => {
  query.keyword = ''
  query.role = ''
  query.status = undefined
  handleSearch()
}

// ── 编辑弹窗（B2-4：此前管理端只能删，没有编辑/改状态的入口）────────────────
const dialogVisible = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)
const form = reactive({
  username: '',
  email: '',
  phone: '',
  qq: '',
  wechat: '',
  role: 'student',
  status: 1,
  password: '',
})

const openEdit = (row: UserItem) => {
  editingId.value = row.id
  form.username = row.username
  form.email = row.email ?? ''
  form.phone = row.phone ?? ''
  form.qq = row.qq ?? ''
  form.wechat = row.wechat ?? ''
  form.role = row.role
  form.status = row.status
  form.password = ''
  dialogVisible.value = true
}

const submitEdit = async () => {
  if (editingId.value === null) return
  saving.value = true
  try {
    // 空串发给后端 = 清空该字段（后端会把 "" 规范化为 NULL）
    const payload: Record<string, any> = {
      email: form.email,
      phone: form.phone,
      qq: form.qq,
      wechat: form.wechat,
      role: form.role,
      status: form.status,
    }
    if (form.password) payload.password = form.password
    await put(`/v1/admin/users/${editingId.value}`, payload)
    ElMessage.success('保存成功')
    dialogVisible.value = false
    fetchData()
  } catch {
    // error handled by interceptor
  } finally {
    saving.value = false
  }
}

const handleStatusChange = async (row: UserItem) => {
  try {
    await put(`/v1/admin/users/${row.id}`, { status: row.status })
    ElMessage.success(row.status === 1 ? '已启用' : '已禁用')
  } catch {
    // 失败要把开关拨回去，否则界面显示的状态与库里不一致
    row.status = row.status === 1 ? 0 : 1
  }
}

const handleDelete = async (row: UserItem) => {
  let stats: UserStats | null = null
  try {
    stats = await get<UserStats>(`/v1/admin/users/${row.id}/stats`)
  } catch {
    stats = null
  }

  const scope = stats
    ? `将同时删除该用户的：简历 ${stats.resume_count} 份、画像 ${stats.profile_count} 份、` +
      `画像快照 ${stats.snapshot_count} 个、报告 ${stats.report_count} 份、对话 ${stats.chat_session_count} 个。`
    : '该用户的关联数据（简历/画像/快照/报告/对话）将一并删除。'

  try {
    await ElMessageBox.confirm(`${scope}此操作不可恢复。`, `删除用户「${row.username}」`, {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
    })
  } catch {
    return // 取消
  }

  try {
    await remove(`/v1/admin/users/${row.id}`)
    ElMessage.success('删除成功')
    fetchData()
  } catch {
    // error handled by interceptor
  }
}

onMounted(fetchData)
</script>

<template>
  <div>
    <el-card>
      <div class="toolbar">
        <el-input
          v-model="query.keyword"
          placeholder="用户名/邮箱/手机号/QQ/微信"
          style="width: 240px"
          clearable
          @keyup.enter="handleSearch"
        />
        <el-select v-model="query.role" placeholder="角色" clearable style="width: 120px">
          <el-option v-for="o in ROLE_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
        </el-select>
        <el-select v-model="query.status" placeholder="状态" clearable style="width: 120px">
          <el-option label="启用" :value="1" />
          <el-option label="禁用" :value="0" />
        </el-select>
        <el-button type="primary" @click="handleSearch">搜索</el-button>
        <el-button @click="handleReset">重置</el-button>
      </div>

      <el-table v-loading="loading" :data="tableData" stripe>
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="username" label="用户名" min-width="120" />
        <el-table-column prop="email" label="邮箱" min-width="160" />
        <el-table-column prop="phone" label="手机号" width="130" />
        <el-table-column prop="qq" label="QQ" width="120" />
        <el-table-column prop="wechat" label="微信" width="140" />
        <el-table-column label="角色" width="100">
          <template #default="{ row }">
            <el-tag :type="row.role === 'admin' ? 'danger' : ''">{{ roleLabel(row.role) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-switch
              v-model="row.status"
              :active-value="1"
              :inactive-value="0"
              @change="handleStatusChange(row)"
            />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-button type="danger" size="small" @click="handleDelete(row)">删除</el-button>
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

    <el-dialog v-model="dialogVisible" :title="`编辑用户：${form.username}`" width="520px">
      <el-form label-width="80px">
        <el-form-item label="用户名">
          <el-input :model-value="form.username" disabled />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="form.email" placeholder="留空表示不填/清空" />
        </el-form-item>
        <el-form-item label="手机号">
          <el-input v-model="form.phone" maxlength="20" />
        </el-form-item>
        <el-form-item label="QQ">
          <el-input v-model="form.qq" maxlength="20" placeholder="纯数字，5-20 位" />
        </el-form-item>
        <el-form-item label="微信">
          <el-input v-model="form.wechat" maxlength="50" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role" style="width: 100%">
            <el-option v-for="o in ROLE_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="form.status" :active-value="1" :inactive-value="0" />
          <span class="hint">{{ form.status === 1 ? '启用' : '禁用' }}</span>
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="form.password" type="password" show-password placeholder="留空则不修改密码" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.hint {
  margin-left: 8px;
  color: #909399;
  font-size: 13px;
}
</style>
