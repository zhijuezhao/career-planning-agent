<template>
  <div class="welcome-container">
    <div class="welcome-card animate-scale-in">
      <div class="welcome-logo">C</div>
      <h1 class="welcome-title">职业成长，从一份简历开始</h1>
      <p class="welcome-sub">上传简历 → AI 解析画像 → 人岗匹配 → 生成职业发展报告</p>
      <el-button type="primary" size="large" class="start-btn hover-lift press-effect" @click="start">
        开始规划
      </el-button>
      <p class="welcome-hint">已有报告？<router-link to="/" @click.prevent="goBusiness">直接进入成果区</router-link></p>
    </div>
  </div>
</template>
<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useJourneyStore } from '@/stores/journey'

const router = useRouter()
const store = useJourneyStore()

function start() {
  store.markWelcomeSeen()
  store.setGuideStep('resume')
  router.push('/guide/resume')
}
function goBusiness() {
  store.markWelcomeSeen()
  router.push('/')
}
</script>

<style scoped>
.welcome-container {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100vh;
  background: var(--c-bg);
}
.welcome-card {
  width: 480px;
  background: var(--c-surface);
  border-radius: var(--radius-lg);
  padding: var(--space-8);
  box-shadow: var(--shadow-lg);
  border: 1px solid var(--c-bg-mute);
  text-align: center;
}
.welcome-logo {
  width: 64px;
  height: 64px;
  background: var(--c-brand-gradient);
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 28px;
  font-weight: 700;
  margin: 0 auto var(--space-6);
  animation: breathing 3s infinite;
}
.welcome-title {
  font-family: var(--font-display);
  font-size: 22px;
  font-weight: 700;
  color: var(--c-text-1);
  margin-bottom: var(--space-3);
}
.welcome-sub {
  font-size: 14px;
  color: var(--c-text-2);
  margin-bottom: var(--space-6);
}
.start-btn {
  width: 100%;
  border-radius: var(--radius-sm);
  font-size: 15px;
  font-weight: 500;
  height: 44px;
}
.welcome-hint {
  margin-top: var(--space-4);
  font-size: 13px;
  color: var(--c-text-3);
}
.welcome-hint a {
  color: var(--c-brand);
  text-decoration: none;
  font-weight: 500;
  transition: opacity var(--duration-fast) ease;
}
.welcome-hint a:hover {
  opacity: 0.8;
}
</style>