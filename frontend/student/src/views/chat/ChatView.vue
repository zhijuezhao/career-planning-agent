<script setup lang="ts">
/**
 * AI 对话页面
 * 交互实现已抽取为共享组件 `@/components/ChatPanel.vue`（Task 15），
 * 本页与其在业务区的使用方（views/business/ChatView.vue）共用同一份实现，避免重复维护。
 */
import ChatPanel from '@/components/ChatPanel.vue'
</script>

<template>
  <ChatPanel />
</template>
