<script setup lang="ts">
/**
 * 分数徽章组件
 * 展示匹配分数，根据分数自动变色
 */
import { computed } from 'vue'

const props = defineProps<{
  score: number  // 0-100
  size?: 'small' | 'medium' | 'large'
  showLabel?: boolean
}>()

const scoreStyle = computed(() => {
  const s = props.score
  if (s >= 80) return { bg: '#dcfce7', color: '#22c55e' }
  if (s >= 60) return { bg: '#e0e7ff', color: '#6366f1' }
  if (s >= 40) return { bg: '#fef3c7', color: '#f59e0b' }
  return { bg: '#fee2e2', color: '#ef4444' }
})

const sizeMap = {
  small: { width: '36px', height: '36px', font: '12px' },
  medium: { width: '44px', height: '44px', font: '14px' },
  large: { width: '56px', height: '56px', font: '18px' },
}

const currentSize = computed(() => sizeMap[props.size || 'medium'])
</script>

<template>
  <div class="score-badge" :style="{
    width: currentSize.width,
    height: currentSize.height,
    fontSize: currentSize.font,
    background: scoreStyle.bg,
    color: scoreStyle.color,
  }">
    {{ score }}<span v-if="showLabel" class="badge-percent">%</span>
  </div>
</template>

<style scoped>
.score-badge {
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  flex-shrink: 0;
}
.badge-percent {
  font-size: 0.7em;
  margin-left: 1px;
}
</style>
