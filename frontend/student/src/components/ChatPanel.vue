<script setup lang="ts">
/**
 * AI 对话面板（共享组件，Task 15）
 * 从 views/chat/ChatView.vue 抽取而来：会话列表 + 消息流（SSE）+ 快捷问题 + 输入区。
 * 供两处使用：引导区顶栏「AI 对话」进入的业务区 /chat，以及既有的 /chat 路由。
 * 通过 `header-extra` 插槽可由父级注入上下文卡片（如当前画像/报告摘要）。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Promotion } from '@element-plus/icons-vue'
import ChatSessionList from '@/views/chat/ChatSessionList.vue'
import ChatMessage from '@/views/chat/ChatMessage.vue'
import {
  createSession,
  listSessions,
  getSessionDetail,
  deleteSession,
  sendMessage,
  type ChatSession,
  type ChatMessage as ChatMsgType,
} from '@/api/chat'

const QUICK_QUESTIONS = [
  '我的专业适合什么方向？',
  '如何准备秋招？',
  '数据分析师需要什么技能？',
  '帮我分析一下我的简历',
]

const sessions = ref<ChatSession[]>([])
const activeSessionId = ref<string | null>(null)
const messages = ref<ChatMsgType[]>([])
const inputText = ref('')
const isStreaming = ref(false)
const listLoading = ref(false)
const messageContainerRef = ref<HTMLElement | null>(null)
let abortController: AbortController | null = null

const currentSessionTitle = computed(() => {
  const session = sessions.value.find(s => s.id === activeSessionId.value)
  return session?.title || '新对话'
})

const canSend = computed(() =>
  inputText.value.trim().length > 0 && !isStreaming.value && !!activeSessionId.value)

function scrollToBottom(): void {
  nextTick(() => {
    if (messageContainerRef.value) {
      messageContainerRef.value.scrollTop = messageContainerRef.value.scrollHeight
    }
  })
}

async function selectSession(sessionId: string): Promise<void> {
  activeSessionId.value = sessionId
  try {
    const detail = await getSessionDetail(sessionId)
    messages.value = detail.messages || []
    scrollToBottom()
  } catch {
    ElMessage.error('加载消息失败')
  }
}

async function loadSessions(): Promise<void> {
  listLoading.value = true
  try {
    const res = await listSessions({ limit: 50 })
    sessions.value = res.items || []
    if (sessions.value.length > 0 && !activeSessionId.value) {
      await selectSession(sessions.value[0].id)
    }
  } catch {
    ElMessage.error('加载会话列表失败')
  } finally {
    listLoading.value = false
  }
}

async function handleCreateSession(): Promise<void> {
  try {
    const res = await createSession({ title: '新对话' })
    sessions.value.unshift(res)
    activeSessionId.value = res.id
    messages.value = []
    ElMessage.success('新对话已创建')
  } catch {
    ElMessage.error('创建会话失败')
  }
}

async function handleDeleteSession(sessionId: string): Promise<void> {
  try {
    await ElMessageBox.confirm('确定要删除这个对话吗？', '提示', { type: 'warning' })
  } catch {
    return   // 用户取消
  }
  try {
    await deleteSession(sessionId)
    sessions.value = sessions.value.filter(s => s.id !== sessionId)
    if (activeSessionId.value === sessionId) {
      activeSessionId.value = null
      messages.value = []
      if (sessions.value.length > 0) {
        await selectSession(sessions.value[0].id)
      }
    }
    ElMessage.success('删除成功')
  } catch {
    ElMessage.error('删除失败')
  }
}

function handleSend(): void {
  if (!canSend.value || !activeSessionId.value) return
  const content = inputText.value.trim()
  inputText.value = ''

  const userMsg: ChatMsgType = {
    id: Date.now(),
    role: 'user',
    content,
    created_at: new Date().toISOString(),
  }
  const aiMsg: ChatMsgType = {
    id: Date.now() + 1,
    role: 'assistant',
    content: '',
    created_at: new Date().toISOString(),
  }
  messages.value.push(userMsg, aiMsg)
  scrollToBottom()

  isStreaming.value = true
  abortController = sendMessage(activeSessionId.value, content, {
    onToken: (text) => {
      aiMsg.content += text
      scrollToBottom()
    },
    onDone: () => {
      isStreaming.value = false
      abortController = null
      void loadSessions()
    },
    onError: (error) => {
      isStreaming.value = false
      abortController = null
      aiMsg.content = `抱歉，发生了错误：${error}`
      ElMessage.error('消息发送失败')
    },
  })
}

function handleStop(): void {
  if (abortController) {
    abortController.abort()
    abortController = null
    isStreaming.value = false
  }
}

function handleQuickQuestion(question: string): void {
  inputText.value = question
  handleSend()
}

/** 供父级调用：预填并发送一个问题（如「基于我的画像分析」按钮） */
function ask(question: string): void {
  handleQuickQuestion(question)
}

defineExpose({ ask })

onMounted(() => { void loadSessions() })
onBeforeUnmount(() => { abortController?.abort() })
</script>

<template>
  <div class="chat-page">
    <ChatSessionList
      :sessions="sessions"
      :active-id="activeSessionId"
      :loading="listLoading"
      @select="selectSession"
      @create="handleCreateSession"
      @delete="handleDeleteSession"
    />

    <div class="chat-main">
      <div class="chat-header">
        <h2 class="chat-title">{{ currentSessionTitle }}</h2>
        <slot name="header-extra">
          <span class="chat-tip">AI 职业规划师 · 随时为你解答</span>
        </slot>
      </div>

      <div ref="messageContainerRef" class="message-container">
        <div v-if="messages.length === 0" class="welcome-area">
          <div class="welcome-icon">🎯</div>
          <h2 class="welcome-title">你好，我是你的 AI 职业规划师</h2>
          <p class="welcome-desc">
            我可以帮助你了解职业方向、分析岗位匹配、规划成长路径。<br />
            有任何职业发展相关的问题，都可以问我！
          </p>
          <div class="quick-questions">
            <button
              v-for="q in QUICK_QUESTIONS"
              :key="q"
              class="quick-btn"
              @click="handleQuickQuestion(q)"
            >
              {{ q }}
            </button>
          </div>
        </div>

        <template v-else>
          <ChatMessage
            v-for="msg in messages"
            :key="msg.id"
            :role="msg.role"
            :content="msg.content"
            :streaming="msg.role === 'assistant' && isStreaming && msg === messages[messages.length - 1]"
          />
        </template>
      </div>

      <div class="input-area">
        <div class="input-wrapper">
          <textarea
            v-model="inputText"
            class="message-input"
            placeholder="输入你的问题...（Enter发送，Shift+Enter换行）"
            rows="1"
            :disabled="!activeSessionId"
            @keydown.enter.exact.prevent="handleSend"
          />
          <div class="input-actions">
            <button v-if="isStreaming" class="stop-btn" @click="handleStop">停止生成</button>
            <button v-else class="send-btn" :disabled="!canSend" @click="handleSend">
              <el-icon :size="18"><Promotion /></el-icon>
            </button>
          </div>
        </div>
        <p class="input-hint">AI 回答仅供参考，重要决策请结合实际情况</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-page {
  display: flex;
  height: calc(100vh - var(--header-height) - var(--space-12));
  background: var(--c-bg);
  border-radius: var(--radius-lg);
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.chat-header {
  padding: var(--space-4) var(--space-6);
  background: var(--c-surface);
  border-bottom: 1px solid var(--c-bg-mute);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
}
.chat-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--c-text-1);
  margin: 0;
}
.chat-tip {
  font-size: var(--text-sm);
  color: var(--c-text-3);
}
.message-container {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-6);
  background: var(--c-bg);
}
.welcome-area {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 400px;
  text-align: center;
}
.welcome-icon {
  font-size: 48px;
  margin-bottom: var(--space-4);
}
.welcome-title {
  font-size: 22px;
  font-weight: 600;
  color: var(--c-text-1);
  margin: 0 0 var(--space-3);
}
.welcome-desc {
  font-size: var(--text-base);
  color: var(--c-text-3);
  line-height: 1.7;
  margin: 0 0 var(--space-6);
}
.quick-questions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  justify-content: center;
  max-width: 600px;
}
.quick-btn {
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-full);
  border: 1px solid var(--c-bg-mute);
  background: var(--c-surface);
  color: var(--c-text-2);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: border-color var(--duration-normal) var(--ease-out),
    color var(--duration-normal) var(--ease-out),
    background var(--duration-normal) var(--ease-out),
    transform var(--duration-normal) var(--ease-out);
}
.quick-btn:hover {
  border-color: var(--c-brand);
  color: var(--c-brand);
  background: var(--c-brand-lighter);
  transform: translateY(-2px);
}
.input-area {
  padding: var(--space-4) var(--space-6);
  background: var(--c-surface);
  border-top: 1px solid var(--c-bg-mute);
}
.input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: var(--space-3);
  background: var(--c-bg);
  border: 1px solid var(--c-bg-mute);
  border-radius: var(--radius-lg);
  padding: var(--space-3);
  transition: border-color var(--duration-fast) ease;
}
.input-wrapper:focus-within {
  border-color: var(--c-brand);
}
.message-input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: var(--text-base);
  line-height: 1.5;
  resize: none;
  max-height: 120px;
  color: var(--c-text-1);
  font-family: inherit;
}
.message-input::placeholder {
  color: var(--c-text-3);
}
.message-input:disabled {
  cursor: not-allowed;
}
.input-actions {
  display: flex;
  align-items: center;
}
.send-btn {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-full);
  border: none;
  background: var(--c-brand);
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background var(--duration-fast) ease, transform var(--duration-fast) ease;
}
.send-btn:hover:not(:disabled) {
  background: var(--c-brand-dark);
  transform: scale(1.05);
}
.send-btn:disabled {
  background: var(--c-bg-mute);
  color: var(--c-text-3);
  cursor: not-allowed;
}
.stop-btn {
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-full);
  border: 1px solid var(--c-danger);
  background: transparent;
  color: var(--c-danger);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: background var(--duration-fast) ease, color var(--duration-fast) ease;
}
.stop-btn:hover {
  background: var(--c-danger);
  color: #fff;
}
.input-hint {
  font-size: var(--text-xs);
  color: var(--c-text-3);
  margin: var(--space-2) 0 0;
  text-align: center;
}
</style>
