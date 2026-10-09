<script setup lang="ts">
/**
 * 通用区块卡片组件
 * 带标题的卡片容器，支持操作按钮区域
 */
defineProps<{
  title?: string
  subtitle?: string
  noPadding?: boolean
}>()
</script>

<template>
  <div class="section-card">
    <div v-if="title || $slots.header" class="card-header">
      <div class="header-left">
        <span v-if="title" class="card-title">{{ title }}</span>
        <span v-if="subtitle" class="card-subtitle">{{ subtitle }}</span>
      </div>
      <div class="header-right">
        <slot name="header"></slot>
      </div>
    </div>
    <div class="card-body" :class="{ 'no-padding': noPadding }">
      <slot></slot>
    </div>
  </div>
</template>

<style scoped>
.section-card {
  background: var(--c-surface);
  border-radius: var(--radius-md);
  border: 1px solid var(--c-bg-mute);
  box-shadow: var(--shadow-xs);
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--c-bg-mute);
}
.header-left {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--c-text-1);
}
.card-subtitle {
  font-size: 12px;
  color: var(--c-text-3);
}
.card-body {
  padding: var(--space-5);
}
.card-body.no-padding {
  padding: 0;
}
</style>
