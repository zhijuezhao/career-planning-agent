<script setup lang="ts">
import { Document } from '@element-plus/icons-vue'
</script>

<template>
  <div class="module-placeholder">
    <div class="placeholder-card hover-lift">
      <el-icon :size="48" color="var(--c-brand-light)"><Document /></el-icon>
      <h2>职业报告</h2>
      <p>生成专业的职业测评报告，深入了解你的职业倾向</p>
      <el-tag type="info" effect="plain" round>开发中</el-tag>
    </div>
  </div>
</template>

<style scoped>
.module-placeholder {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 60vh;
}
.placeholder-card {
  text-align: center;
  background: var(--c-surface);
  border: 1px solid var(--c-bg-mute);
  border-radius: var(--radius-lg);
  padding: var(--space-8);
  box-shadow: var(--shadow-sm);
  max-width: 400px;
}
.placeholder-card h2 {
  margin-top: var(--space-5);
  font-size: 20px;
  font-weight: 600;
  color: var(--c-text-1);
}
.placeholder-card p {
  margin-top: var(--space-3);
  font-size: 14px;
  color: var(--c-text-3);
  line-height: 1.6;
}
.placeholder-card .el-tag {
  margin-top: var(--space-5);
}
</style>
