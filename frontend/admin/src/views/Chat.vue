<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { get, post, put, remove } from '@/api/request'

interface ChatSession {
  id: string
  user_id: number
  title: string | null
  created_at: string
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
})

const fetchSessions = async () => {
  loading.value = true
  try {
    const res = await get<{ items: ChatSession[]; total: number }>('/v1/admin/chat/sessions', {
      params: { skip: (query.page - 1) * query.limit, limit: query.limit },
    })
    sessionData.value = res.items
    sessionTotal.value = res.total
  } catch {
    // error handled by interceptor
  } finally {
    loading.value = false
  }
}

const fetchMessages = async (sessionId?: string) => {
  loading.value = true
  try {
    const params: Record<string, any> = {
      skip: (query.page - 1) * query.limit,
      limit: query.limit,
    }
    if (sessionId) params.session_id = sessionId
    const res = await get<{ items: ChatMessage[]; total: number }>('/v1/admin/chat/messages', { params })
    messageData.value = res.items
    messageTotal.value = res.total
  } catch {
    // error handled by interceptor
  } finally {
    loading.value = false
  }
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
    fetchMessages(selectedSessionId.value || undefined)
  }
}

onMounted(fetchSessions)
</script>

<template>
  <div>
    <el-card class="data-card">
      <el-tabs v-model="activeTab" @tab-change="handleTabChange">
        <el-tab-pane label="会话列表" name="sessions">
          <el-table v-loading="loading" :data="sessionData" stripe>
            <el-table-column prop="id" label="会话ID" width="280" />
            <el-table-column prop="user_id" label="用户ID" width="100" />
            <el-table-column prop="title" label="标题" />
            <el-table-column label="创建时间" width="180">
              <template #default="{ row }">
                {{ new Date(row.created_at).toLocaleString() }}
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100">
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
          <el-table v-loading="loading" :data="messageData" stripe>
            <el-table-column prop="id" label="ID" width="80" />
            <el-table-column prop="session_id" label="会话ID" width="280" />
            <el-table-column label="角色" width="100">
              <template #default="{ row }">
                <el-tag :type="row.role === 'user' ? '' : 'success'" size="small">
                  {{ row.role }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="content" label="内容" show-overflow-tooltip />
            <el-table-column label="Token" width="80">
              <template #default="{ row }">
                {{ row.tokens_used }}
              </template>
            </el-table-column>
            <el-table-column label="创建时间" width="180">
              <template #default="{ row }">
                {{ new Date(row.created_at).toLocaleString() }}
              </template>
            </el-table-column>
          </el-table>
          <el-pagination
            v-model:current-page="query.page"
            :page-size="query.limit"
            :total="messageTotal"
            layout="total, prev, pager, next"
            @current-change="() => fetchMessages(selectedSessionId || undefined)"
          />
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<style scoped>
.data-card {
  border-radius: 12px;
  border: 1px solid #e6e6e6;
}
</style>
