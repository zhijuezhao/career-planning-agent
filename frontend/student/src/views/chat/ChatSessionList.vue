/**
 * 聊天会话列表组件
 * 左侧边栏，展示历史会话，支持新建/切换/删除
 */
<script setup lang="ts">

import { Plus, Delete, ChatLineSquare } from '@element-plus/icons-vue'
import type { ChatSession } from '@/api/chat'

interface Props {
  sessions: ChatSession[]
  activeId: string | null
  loading?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  loading: false,
})

const emit = defineEmits<{
  select: [id: string]
  create: []
  delete: [id: string]
}>()

// 格式化日期为友好显示
function formatDate(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - date.getTime()

  // 1分钟内
  if (diff < 60000) return '刚刚'
  // 1小时内
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`
  // 今天
  if (date.toDateString() === now.toDateString()) {
    return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`
  }
  // 昨天
  const yesterday = new Date(now)
  yesterday.setDate(yesterday.getDate() - 1)
  if (date.toDateString() === yesterday.toDateString()) return '昨天'
  // 更早
  return `${date.getMonth() + 1}/${date.getDate()}`
}

// 会话标题（无标题时显示"新对话"）
function sessionTitle(session: ChatSession): string {
  return session.title || '新对话'
}
</script>

<template>
  <div class="session-list">
    <!-- 顶部：新建对话按钮 -->
    <div class="list-header">
      <h3 class="list-title">对话记录</h3>
      <button class="new-chat-btn" @click="emit('create')" title="新建对话">
        <el-icon :size="18"><Plus /></el-icon>
      </button>
    </div>

    <!-- 会话列表 -->
    <div class="list-content">
      <!-- 空状态 -->
      <div v-if="!loading && sessions.length === 0" class="empty-state">
        <el-icon :size="32" color="var(--c-text-3)"><ChatLineSquare /></el-icon>
        <p>暂无对话记录</p>
        <span>点击上方按钮开始新对话</span>
      </div>

      <!-- 会话项 -->
      <div
        v-for="session in sessions"
        :key="session.id"
        class="session-item"
        :class="{ active: session.id === activeId }"
        @click="emit('select', session.id)"
      >
        <div class="session-info">
          <span class="session-title">{{ sessionTitle(session) }}</span>
          <span class="session-time">{{ formatDate(session.updated_at) }}</span>
        </div>
        <button
          class="delete-btn"
          @click.stop="emit('delete', session.id)"
          title="删除对话"
        >
          <el-icon :size="14"><Delete /></el-icon>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.session-list {
  width: 260px;
  height: 100%;
  background: var(--c-surface);
  border-right: 1px solid var(--c-bg-mute);
  display: flex;
  flex-direction: column;
}

/* 顶部 */
.list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-4);
  border-bottom: 1px solid var(--c-bg-mute);
}

.list-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--c-text-1);
  margin: 0;
}

.new-chat-btn {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--c-bg-mute);
  background: var(--c-bg);
  color: var(--c-text-2);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--duration-fast) ease;
}

.new-chat-btn:hover {
  border-color: var(--c-brand);
  color: var(--c-brand);
  background: var(--c-brand-lighter);
}

/* 列表内容 */
.list-content {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-2);
}

/* 空状态 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-8) var(--space-4);
  text-align: center;
  gap: var(--space-2);
}

.empty-state p {
  margin: 0;
  font-size: 14px;
  color: var(--c-text-2);
}

.empty-state span {
  font-size: 12px;
  color: var(--c-text-3);
}

/* 会话项 */
.session-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all var(--duration-fast) ease;
  margin-bottom: var(--space-1);
}

.session-item:hover {
  background: var(--c-bg-soft);
}

.session-item.active {
  background: var(--c-brand-lighter);
  border-left: 3px solid var(--c-brand);
}

.session-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.session-title {
  font-size: 14px;
  color: var(--c-text-1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-time {
  font-size: 12px;
  color: var(--c-text-3);
}

.session-item.active .session-title {
  color: var(--c-brand);
  font-weight: 500;
}

/* 删除按钮 */
.delete-btn {
  width: 24px;
  height: 24px;
  border-radius: var(--radius-sm);
  border: none;
  background: transparent;
  color: var(--c-text-3);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: all var(--duration-fast) ease;
}

.session-item:hover .delete-btn {
  opacity: 1;
}

.delete-btn:hover {
  background: var(--c-danger);
  color: #fff;
}
</style>
