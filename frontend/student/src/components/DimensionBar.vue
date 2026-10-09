<script setup lang="ts">
/**
 * 维度评分条组件
 * 展示单个维度的评分进度条，支持颜色自动适配
 */
import { computed } from 'vue'

const props = defineProps<{
  label: string       // 维度名称
  value: number       // 当前值
  max?: number        // 最大值（默认5）
  showValue?: boolean // 是否显示数值
  color?: string      // 自定义颜色
}>()

const max = computed(() => props.max || 5)
const percentage = computed(() => Math.min((props.value / max.value) * 100, 100))

const barColor = computed(() => {
  if (props.color) return props.color
  const ratio = props.value / max.value
  if (ratio >= 0.8) return '#22c55e'
  if (ratio >= 0.6) return '#6366f1'
  if (ratio >= 0.4) return '#f59e0b'
  return '#ef4444'
})
</script>

<template>
  <div class="dimension-bar">
    <span class="dim-label">{{ label }}</span>
    <div class="dim-bar-bg">
      <div
        class="dim-bar-fill"
        :style="{ width: `${percentage}%`, backgroundColor: barColor }"
      ></div>
    </div>
    <span v-if="showValue !== false" class="dim-value" :style="{ color: barColor }">
      {{ value.toFixed(1) }}
    </span>
  </div>
</template>

<style scoped>
.dimension-bar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.dim-label {
  width: 80px;
  font-size: 12px;
  color: var(--c-text-3);
  flex-shrink: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dim-bar-bg {
  flex: 1;
  height: 6px;
  background: var(--c-bg-soft);
  border-radius: var(--radius-full);
  overflow: hidden;
}
.dim-bar-fill {
  height: 100%;
  border-radius: var(--radius-full);
  transition: width 0.6s ease;
}
.dim-value {
  width: 32px;
  font-size: 12px;
  font-weight: 600;
  text-align: right;
  flex-shrink: 0;
}

@media (max-width: 768px) {
  .dim-label {
    width: 60px;
  }
}
</style>
