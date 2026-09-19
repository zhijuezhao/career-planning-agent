<script setup lang="ts">
/**
 * 总览统计卡（Task 13）
 * 克制：白底卡 + 图标徽章 + 大数值 + 说明文字；数值缺失时显示占位符。
 */
defineProps<{
  label: string
  value: number | string
  suffix?: string
  icon?: unknown
  hint?: string
  muted?: boolean
}>()
</script>

<template>
  <div class="stat-card" :class="{ 'is-muted': muted }">
    <div class="stat-head">
      <span v-if="icon" class="stat-icon">
        <el-icon :size="18"><component :is="icon" /></el-icon>
      </span>
      <span class="stat-label">{{ label }}</span>
    </div>
    <p class="stat-value">
      {{ value }}<span v-if="suffix" class="stat-suffix">{{ suffix }}</span>
    </p>
    <p v-if="hint" class="stat-hint">{{ hint }}</p>
  </div>
</template>

<style scoped>
.stat-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-5);
  background: var(--c-surface);
  border: 1px solid var(--c-bg-mute);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-xs);
  transition: box-shadow var(--duration-normal) var(--ease-out);
}
.stat-card:hover {
  box-shadow: var(--shadow-md);
}
.stat-card.is-muted .stat-value {
  color: var(--c-text-3);
}
.stat-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}
.stat-icon {
  flex: none;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  background: var(--c-brand-lighter);
  color: var(--c-brand);
}
.stat-label {
  font-size: var(--text-sm);
  color: var(--c-text-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.stat-value {
  margin: 0;
  font-family: var(--font-display);
  font-size: 28px;
  font-weight: 700;
  line-height: 1.1;
  color: var(--c-text-1);
}
.stat-suffix {
  margin-left: var(--space-1);
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--c-text-3);
}
.stat-hint {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--c-text-3);
  line-height: 1.5;
}
</style>
