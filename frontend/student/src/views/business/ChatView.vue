<script setup lang="ts">
/**
 * 业务区 - AI 对话（Task 15）
 * 复用共享 ChatPanel（会话列表 + SSE 消息流 + 快捷问题）。
 * 上下文：后端 sendMessage 协议体仅支持 { content }（无上下文参数），
 * 因此这里只把当前画像/报告作为**只读提示**展示在标题栏，不伪造上下文注入（R-15.2）。
 */
import { computed, onMounted } from 'vue'
import ChatPanel from '@/components/ChatPanel.vue'
import { useJourneyStore } from '@/stores/journey'

const journey = useJourneyStore()

const contextHint = computed(() => {
  const parts: string[] = []
  if (journey.snapshotId) parts.push(`画像快照 #${journey.snapshotId}`)
  if (journey.reportVersions > 0) parts.push(`${journey.reportVersions} 份报告`)
  return parts.length ? parts.join(' · ') : '暂无画像或报告'
})

onMounted(async () => {
  try {
    await journey.fetchStatus()
  } catch {
    /* 离线等场景忽略：提示降级为「暂无画像或报告」 */
  }
})
</script>

<template>
  <div class="business-chat">
    <ChatPanel>
      <template #header-extra>
        <span class="context-chip" :title="`当前上下文：${contextHint}`">
          当前上下文：{{ contextHint }}
        </span>
      </template>
    </ChatPanel>
  </div>
</template>

<style scoped>
.business-chat {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.context-chip {
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-full);
  background: var(--c-brand-lighter);
  color: var(--c-brand);
  font-size: var(--text-xs);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 320px;
}
</style>
