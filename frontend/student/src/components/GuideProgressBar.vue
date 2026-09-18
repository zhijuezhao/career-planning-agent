<!-- frontend/student/src/components/GuideProgressBar.vue；纯展示，无 emit（回跳由父层 GuideLayout 的「上一步」管理） -->
<script setup lang="ts">
import type { GuideStepMeta } from '@/constants/journey'
defineProps<{ steps: GuideStepMeta[]; current: string }>()
</script>
<template>
  <nav class="guide-progress" aria-label="引导进度">
    <div v-for="(s, i) in steps" :key="s.key" class="gp-node"
         :class="{ current: s.key === current, done: s.key !== current && i < steps.findIndex(x => x.key === current) }">
      <span class="gp-dot">{{ i + 1 }}</span>
      <span class="gp-label">{{ s.label }}</span>
    </div>
  </nav>
</template>
<style scoped>
/* 克制：flex 横向平分 5 节点；圆点 32px radius-full；连线 1px var(--c-bg-mute)；
   current 用 var(--c-brand) 填充点；done 打勾色 var(--c-success)；transition var(--duration-fast) */
.guide-progress {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-4);
  padding: var(--space-5) var(--space-6);
  border-bottom: 1px solid var(--c-bg-mute);
  background: var(--c-surface);
}
.gp-node {
  position: relative;
  flex: 1;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}
/* 节点连线：1px 中性色，最后一个节点不画 */
.gp-node:not(:last-child)::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--c-bg-mute);
}
.gp-dot {
  flex: none;
  width: var(--space-8);
  height: var(--space-8);
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--c-text-3);
  border: 1px solid var(--c-bg-mute);
  background: var(--c-surface);
  transition: background var(--duration-fast) ease, border-color var(--duration-fast) ease,
    color var(--duration-fast) ease;
}
.gp-label {
  flex: none;
  font-size: var(--text-sm);
  color: var(--c-text-3);
  white-space: nowrap;
  transition: color var(--duration-fast) ease;
}
.gp-node.done .gp-dot {
  background: var(--c-success);
  border-color: var(--c-success);
  color: #fff;
}
.gp-node.done .gp-label {
  color: var(--c-text-2);
}
.gp-node.current .gp-dot {
  background: var(--c-brand);
  border-color: var(--c-brand);
  color: #fff;
}
.gp-node.current .gp-label {
  color: var(--c-text-1);
  font-weight: 600;
}
</style>
