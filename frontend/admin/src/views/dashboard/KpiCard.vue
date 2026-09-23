<script setup lang="ts">
/** KPI 卡（P1-6）：一个数字 + 一个标签 + 一处配色点缀 */
defineProps<{
  label: string
  value: number
  color: string
}>()
</script>

<template>
  <div class="kpi-card" :class="`tone-${color}`">
    <div class="kpi-value">{{ value ?? 0 }}</div>
    <div class="kpi-label">{{ label }}</div>
  </div>
</template>

<style scoped>
.kpi-card {
  background: #fff;
  border: 1px solid #e6e6e6;
  border-radius: 12px;
  padding: 16px 18px;
  height: 100%;
  box-sizing: border-box;
  transition: box-shadow 0.2s, transform 0.2s;
}

.kpi-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  transform: translateY(-2px);
}

.kpi-value {
  font-size: 26px;
  font-weight: 700;
  color: #1f2937;
  line-height: 1.2;
}

.kpi-label {
  margin-top: 6px;
  font-size: 13px;
  color: #909399;
}

.kpi-card.tone-blue {
  border-left: 3px solid #667eea;
}
.kpi-card.tone-green {
  border-left: 3px solid #22c55e;
}
.kpi-card.tone-orange {
  border-left: 3px solid #f97316;
}
.kpi-card.tone-purple {
  border-left: 3px solid #a855f7;
}
.kpi-card.tone-cyan {
  border-left: 3px solid #06b6d4;
}
.kpi-card.tone-pink {
  border-left: 3px solid #ec4899;
}
</style>
