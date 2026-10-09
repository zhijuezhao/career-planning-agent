<script setup lang="ts">
/**
 * 空状态组件
 * 统一的空状态展示，支持图标、描述、操作按钮
 */
defineProps<{
  title?: string
  description?: string
  icon?: any
  showAction?: boolean
  actionText?: string
}>()

defineEmits<{
  action: []
}>()
</script>

<template>
  <div class="empty-state">
    <el-icon v-if="icon" :size="48" color="var(--c-text-3)">
      <component :is="icon" />
    </el-icon>
    <h3 v-if="title">{{ title }}</h3>
    <p v-if="description">{{ description }}</p>
    <el-button v-if="showAction" type="primary" @click="$emit('action')">
      {{ actionText || '去操作' }}
    </el-button>
  </div>
</template>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 200px;
  text-align: center;
  gap: var(--space-3);
  padding: var(--space-6);
}
.empty-state h3 {
  font-size: 16px;
  font-weight: 600;
  color: var(--c-text-1);
  margin: 0;
}
.empty-state p {
  font-size: 13px;
  color: var(--c-text-3);
  line-height: 1.5;
  margin: 0;
  max-width: 300px;
}
</style>
