<script setup lang="ts">
defineProps<{ title: string; description: string }>()
</script>

<template>
  <section class="journey-shell">
    <h2 class="journey-shell-title">{{ title }}</h2>
    <p class="journey-shell-desc">{{ description }}</p>
    <div class="journey-shell-empty">
      <p>该阶段将在后续迭代中实现</p>
    </div>
  </section>
</template>

<style scoped>
.journey-shell {
  max-width: 720px;
  margin: 0 auto;
  text-align: center;
}
.journey-shell-title {
  font-family: var(--font-display);
  font-size: 28px;
  font-weight: 600;
  color: var(--c-text-1);
  margin-bottom: var(--space-3);
}
.journey-shell-desc {
  font-size: 15px;
  color: var(--c-text-2);
  margin-bottom: var(--space-8);
}
.journey-shell-empty {
  background: var(--c-surface);
  border: 1px solid var(--c-bg-mute);
  border-radius: var(--radius-md);
  padding: var(--space-8);
  color: var(--c-text-3);
}
</style>