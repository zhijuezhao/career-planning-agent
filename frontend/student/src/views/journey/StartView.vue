<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const userStore = useUserStore()

function enter() {
  if (userStore.token) router.push('/upload')
  else router.push({ path: '/login', query: { redirect: '/upload' } })
}
</script>

<template>
  <section class="start-view">
    <h1 class="start-title">大学生职业规划智能体</h1>
    <p class="start-sub">上传你的简历，从自我认知开始，走完从画像到报告的完整成长旅程。</p>
    <button class="start-cta hover-lift press-effect" @click="enter">开始我的成长旅程</button>
  </section>
</template>

<style scoped>
.start-view {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  gap: var(--space-6);
  padding: var(--space-8);
  background: var(--c-bg);
}
.start-title {
  font-family: var(--font-display);
  font-size: 40px;
  font-weight: 700;
  color: var(--c-text-1);
}
.start-sub {
  font-size: 17px;
  color: var(--c-text-2);
  max-width: 480px;
  line-height: 1.7;
}
.start-cta {
  padding: 14px 40px;
  border-radius: var(--radius-full);
  background: var(--c-brand-gradient);
  color: #fff;
  font-size: 16px;
  font-weight: 600;
  border: none;
  cursor: pointer;
  margin-top: var(--space-6);
}
</style>