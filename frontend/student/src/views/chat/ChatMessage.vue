/**
 * 聊天消息组件
 * 展示单条消息，支持用户/AI两种角色样式
 * 支持流式打字效果（streaming模式）
 */
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { UserFilled, Cpu } from '@element-plus/icons-vue'

interface Props {
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  streaming: false,
})

// 流式显示的内容（打字机效果）
const displayContent = ref('')
const isStreaming = ref(false)

// 监听content变化，实现流式打字效果
watch(
  () => props.content,
  (newVal) => {
    if (!props.streaming) {
      displayContent.value = newVal
      return
    }

    // 流式模式：直接显示完整内容（浏览器渲染更快）
    displayContent.value = newVal
    if (newVal.length > 0) {
      isStreaming.value = true
    }
  },
  { immediate: true }
)

// 是否为AI消息
const isAssistant = computed(() => props.role === 'assistant')
</script>

<template>
  <div class="chat-message" :class="{ 'is-user': !isAssistant, 'is-assistant': isAssistant }">
    <!-- 头像 -->
    <div class="message-avatar" :class="isAssistant ? 'avatar-ai' : 'avatar-user'">
      <el-icon :size="16">
        <Cpu v-if="isAssistant" />
        <UserFilled v-else />
      </el-icon>
    </div>

    <!-- 消息内容 -->
    <div class="message-body">
      <div class="message-role-label">
        {{ isAssistant ? 'AI 职业规划师' : '我' }}
      </div>
      <div class="message-bubble">
        <p class="message-text">{{ displayContent }}<span v-if="streaming && isStreaming" class="typing-cursor" /></p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-message {
  display: flex;
  gap: var(--space-3);
  margin-bottom: var(--space-5);
  animation: messageSlideIn 0.3s var(--ease-out);
}

@keyframes messageSlideIn {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.is-user {
  flex-direction: row-reverse;
}

/* 头像 */
.message-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: #fff;
}

.avatar-ai {
  background: var(--c-brand-gradient);
}

.avatar-user {
  background: linear-gradient(135deg, #22c55e, #16a34a);
}

/* 消息主体 */
.message-body {
  max-width: 70%;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.is-user .message-body {
  align-items: flex-end;
}

.message-role-label {
  font-size: 12px;
  color: var(--c-text-3);
  padding: 0 var(--space-1);
}

/* 气泡 */
.message-bubble {
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-lg);
  line-height: 1.7;
  font-size: 14px;
  word-break: break-word;
}

.is-assistant .message-bubble {
  background: var(--c-surface);
  border: 1px solid var(--c-bg-mute);
  border-top-left-radius: 4px;
  color: var(--c-text-1);
}

.is-user .message-bubble {
  background: var(--c-brand);
  color: #fff;
  border-top-right-radius: 4px;
}

.message-text {
  margin: 0;
  white-space: pre-wrap;
}

/* 流式打字光标 */
.typing-cursor {
  display: inline-block;
  width: 2px;
  height: 16px;
  background: var(--c-brand);
  margin-left: 2px;
  animation: blink 0.8s infinite;
  vertical-align: text-bottom;
}

@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}
</style>
