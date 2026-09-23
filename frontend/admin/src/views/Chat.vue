<script setup lang="ts">
/**
 * 对话记录（P1-5，需求 6）
 *
 * 本轮只做两件事（其他字段按需求「暂不修改」）：
 * 1. 筛选：时间范围（两个 tab 都有）+ 消息的角色 / 关键字；
 * 2. 消息内容改为「摘要 + 预览卡」—— 统一用 `DetailDialog`（Markdown 预览 + JSON）。
 */
import { onMounted, reactive, ref } from 'vue'
import { get } from '@/api/request'
import { DetailDialog } from '@/components'
import type { DetailTag } from '@/components'
import { formatDateTime } from '@/utils/preview'

interface ChatSession {
  id: string
  user_id: number
  title: string | null
  summary: string | null
  created_at: string
  updated_at: string
}

interface ChatMessage {
  id: number
  session_id: string
  role: string
  content: string
  tokens_used: number
  model_used: string | null
  created_at: string
}

const loading = ref(false)
const sessionData = ref<ChatSession[]>([])
const messageData = ref<ChatMessage[]>([])
const sessionTotal = ref(0)
const messageTotal = ref(0)
const activeTab = ref('sessions')
const selectedSessionId = ref<string | null>(null)

const query = reactive({
  page: 1,
  limit: 20,
  range: null as [Date, Date] | null,
  keyword: '',
  role: '' as '' | 'user' | 'assistant' | 'system',
})

/** 时间范围 → ISO8601（后端按 timestamptz 闭区间比较） */
const timeParams = (): Record<string, string> => {
  const params: Record<string, string> = {}
  const [start, end] = query.range ?? []
  if (start) params.start = new Date(start).toISOString()
  if (end) params.end = new Date(end).toISOString()
  return params
}

const fetchSessions = async () => {
  loading.value = true
  try {
    const params: Record<string, unknown> = {
      skip: (query.page - 1) * query.limit,
      limit: query.limit,
      ...timeParams(),
    }
    if (query.keyword) params.keyword = query.keyword
    const res = await get<{ items: ChatSession[]; total: number }>('/v1/admin/chat/sessions', {
      params,
    })
    sessionData.value = res.items
    sessionTotal.value = res.total
  } catch {
    // error handled by interceptor
  } finally {
    loading.value = false
  }
}

const fetchMessages = async (sessionId?: string | null) => {
  loading.value = true
  try {
    const params: Record<string, unknown> = {
      skip: (query.page - 1) * query.limit,
      limit: query.limit,
      ...timeParams(),
    }
    const sid = sessionId ?? selectedSessionId.value
    if (sid) params.session_id = sid
    if (query.keyword) params.keyword = query.keyword
    if (query.role) params.role = query.role
    const res = await get<{ items: ChatMessage[]; total: number }>('/v1/admin/chat/messages', {
      params,
    })
    messageData.value = res.items
    messageTotal.value = res.total
  } catch {
    // error handled by interceptor
  } finally {
    loading.value = false
  }
}

const handleSearch = () => {
  query.page = 1
  if (activeTab.value === 'sessions') fetchSessions()
  else fetchMessages()
}

const handleReset = () => {
  query.range = null
  query.keyword = ''
  query.role = ''
  handleSearch()
}

const handleViewSession = (row: ChatSession) => {
  selectedSessionId.value = row.id
  activeTab.value = 'messages'
  query.page = 1
  fetchMessages(row.id)
}

const handleTabChange = (tab: string) => {
  query.page = 1
  if (tab === 'sessions') {
    selectedSessionId.value = null
    fetchSessions()
  } else {
    fetchMessages()
  }
}

const roleLabel = (role: string) =>
  role === 'user' ? '用户' : role === 'assistant' ? '助手' : role

const preview = (text: string | null, max = 90) => {
  const value = (text ?? '').replace(/\s+/g, ' ').trim()
  return value.length > max ? `${value.slice(0, max)}…` : value || '-'
}

// ── 消息内容预览卡 ──────────────────────────────────────────────────────────

const detailVisible = ref(false)
const detailTitle = ref('')
const detailSubtitle = ref('')
const detailTags = ref<DetailTag[]>([])
const detailMarkdown = ref('')
const detailJson = ref<unknown>(undefined)

const openMessage = (row: ChatMessage) => {
  detailTitle.value = `对话消息 #${row.id}`
  detailSubtitle.value = `会话 ${row.session_id}`
  const tags: DetailTag[] = [
    { text: roleLabel(row.role), type: row.role === 'user' ? 'primary' : 'success' },
  ]
  if (row.model_used) tags.push({ text: row.model_used, type: 'info' })
  tags.push({ text: `${row.tokens_used} tokens`, type: 'info' })
  detailTags.value = tags
  detailMarkdown.value = row.content
  detailJson.value = row
  detailVisible.value = true
}

onMounted(fetchSessions)
</script>

<template>
  <div>
    <el-card class="data-card">
      <div class="toolbar">
        <el-date-picker
          v-model="query.range"
          type="datetimerange"
          range-separator="至"
          start-placeholder="开始时间"
          end-placeholder="结束时间"
          style="width: 380px"
        />
        <el-input
          v-model="query.keyword"
          :placeholder="activeTab === 'sessions' ? '标题/摘要关键字' : '消息内容关键字'"
          style="width: 210px"
          clearable
          @keyup.enter="handleSearch"
        />
        <el-select
          v-if="activeTab === 'messages'"
          v-model="query.role"
          placeholder="角色"
          style="width: 130px"
          clearable
        >
          <el-option label="用户" value="user" />
          <el-option label="助手" value="assistant" />
          <el-option label="系统" value="system" />
        </el-select>
        <el-button type="primary" @click="handleSearch">搜索</el-button>
        <el-button @click="handleReset">重置</el-button>
      </div>

      <el-tabs v-model="activeTab" @tab-change="handleTabChange">
        <el-tab-pane label="会话列表" name="sessions">
          <el-table v-loading="loading" :data="sessionData" stripe>
            <el-table-column prop="id" label="会话ID" width="280" show-overflow-tooltip />
            <el-table-column prop="user_id" label="用户ID" width="90" />
            <el-table-column prop="title" label="标题" min-width="160" show-overflow-tooltip />
            <el-table-column label="创建时间" width="170">
              <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="最近更新" width="170">
              <template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="90" fixed="right">
              <template #default="{ row }">
                <el-button type="primary" size="small" link @click="handleViewSession(row)">
                  查看
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-pagination
            v-model:current-page="query.page"
            :page-size="query.limit"
            :total="sessionTotal"
            layout="total, prev, pager, next"
            @current-change="fetchSessions"
          />
        </el-tab-pane>

        <el-tab-pane label="消息记录" name="messages">
          <div v-if="selectedSessionId" class="session-hint">
            当前仅看会话
            <el-tag size="small" type="info">{{ selectedSessionId }}</el-tag>
            <el-button size="small" link type="primary" @click="handleTabChange('messages')">
              查看全部
            </el-button>
          </div>

          <el-table v-loading="loading" :data="messageData" stripe>
            <el-table-column prop="id" label="ID" width="80" />
            <el-table-column prop="session_id" label="会话ID" width="260" show-overflow-tooltip />
            <el-table-column label="角色" width="90">
              <template #default="{ row }">
                <el-tag :type="row.role === 'user' ? 'primary' : 'success'" size="small">
                  {{ roleLabel(row.role) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="内容" min-width="260">
              <template #default="{ row }">
                <span class="content-preview">{{ preview(row.content) }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="model_used" label="模型" width="120" show-overflow-tooltip />
            <el-table-column label="Token" width="80">
              <template #default="{ row }">{{ row.tokens_used }}</template>
            </el-table-column>
            <el-table-column label="创建时间" width="170">
              <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="90" fixed="right">
              <template #default="{ row }">
                <el-button type="primary" size="small" link @click="openMessage(row)">预览</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-pagination
            v-model:current-page="query.page"
            :page-size="query.limit"
            :total="messageTotal"
            layout="total, prev, pager, next"
            @current-change="() => fetchMessages()"
          />
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <DetailDialog
      v-model="detailVisible"
      :title="detailTitle"
      :subtitle="detailSubtitle"
      :tags="detailTags"
      :markdown="detailMarkdown"
      :json="detailJson"
      width="860px"
      empty-text="（该消息内容为空）"
    />
  </div>
</template>

<style scoped>
.data-card {
  border-radius: 12px;
  border: 1px solid #e6e6e6;
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

.session-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  font-size: 12px;
  color: #909399;
}

.content-preview {
  color: #606266;
}
</style>
