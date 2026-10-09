<script setup lang="ts">
/**
 * 加载卡片组件
 * 统一的加载状态展示
 */
defineProps<{
  text?: string
  height?: string
}>()
</script>

<template>
  <div class="loading-card" :style="{ minHeight: height || '200px' }">
    <el-icon :size="28" class="is-loading" color="var(--c-brand)">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48l2.83-2.83" />
      </svg>
    </el-icon>
    <p>{{ text || '加载中...' }}</p>
  </div>
</template>

<style scoped>
.loading-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  background: var(--c-surface);
  border-radius: var(--radius-md);
  border: 1px solid var(--c-bg-mute);
  color: var(--c-text-3);
  font-size: 14px;
}
</style>
