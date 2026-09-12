<script setup lang="ts">
export interface StepperItem {
  label: string
  state: 'done' | 'current' | 'locked'
}

defineProps<{ items: StepperItem[] }>()
</script>

<template>
  <nav class="journey-stepper">
    <div
      v-for="item in items"
      :key="item.label"
      class="step"
      :class="`step-${item.state}`"
    >
      <span class="step-dot">
        <span v-if="item.state === 'done'" class="step-check">✓</span>
        <span v-else-if="item.state === 'current'" class="step-breathe"></span>
      </span>
      <span class="step-label">{{ item.label }}</span>
    </div>
  </nav>
</template>

<style scoped>
.journey-stepper {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-4);
  padding: var(--space-5) var(--space-6);
  border-bottom: 1px solid var(--c-bg-mute);
  background: var(--c-surface);
}
.step {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--c-text-3);
}
.step-dot {
  width: 16px;
  height: 16px;
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 700;
}
.step-done .step-dot {
  background: var(--c-stage-done);
  color: #fff;
}
.step-done .step-label {
  color: var(--c-text-2);
}
.step-current .step-dot {
  background: transparent;
  border: 2px solid var(--c-stage-done);
}
.step-current .step-label {
  color: var(--c-text-1);
  font-weight: 600;
}
.step-locked .step-dot {
  border: 1px solid var(--c-bg-mute);
}
.step-breathe {
  width: 6px;
  height: 6px;
  border-radius: var(--radius-full);
  background: var(--c-stage-done);
  animation: breathe 1.8s ease-in-out infinite;
}
.step-check {
  line-height: 1;
}
@keyframes breathe {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.4); opacity: 0.4; }
}
</style>