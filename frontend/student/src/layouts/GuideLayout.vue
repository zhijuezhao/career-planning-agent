<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { GUIDE_STEPS, GUIDE_STEP_MAP } from '@/constants/journey'
import type { GuideStep } from '@/api/journey'
import { useJourneyStore } from '@/stores/journey'
import { useUserStore } from '@/stores/user'
import GuideProgressBar from '@/components/GuideProgressBar.vue'

const route = useRoute()
const router = useRouter()
const journey = useJourneyStore()
const userStore = useUserStore()

const currentStep = computed<GuideStep>(() => (route.meta.guide as GuideStep) ?? 'resume')
const currentIndex = computed(() => GUIDE_STEPS.findIndex(s => s.key === currentStep.value))
const nextStep = computed(() =>
  currentIndex.value >= GUIDE_STEPS.length - 1 ? null : GUIDE_STEPS[currentIndex.value + 1])
const headerText = computed(() => `我在 ${GUIDE_STEP_MAP[currentStep.value].title}`)
const nextText = computed(() => {
  if (currentIndex.value >= GUIDE_STEPS.length - 1) return '旅程已完成，生成报告'
  return `下一步：${GUIDE_STEPS[currentIndex.value + 1].label}`
})
const canAdvance = computed(() => {
  // 每步自检由页面组件调用 journey.setGuideStep(nextKey) 达成；此处只按 store 顺序放行
  // 方案 (b)：store 前端本地 guideStep ≥ 本步 -> 可进一步（按步骤索引比较，见 R-9.5）
  const next = nextStep.value
  if (!next) return true                                   // 最后一步（生成报告页）：按钮常亮
  const doneIndex = GUIDE_STEPS.findIndex(s => s.key === journey.guideStep)
  return doneIndex >= currentIndex.value + 1               // 已走完本步（或更远）才放行
})

function advance() {
  if (currentIndex.value >= GUIDE_STEPS.length - 1) { router.push(GUIDE_STEP_MAP.done.route); return }
  router.push(GUIDE_STEPS[currentIndex.value + 1].route)
}
function back() {
  if (currentIndex.value === 0) { router.push('/welcome'); return }
  router.push(GUIDE_STEPS[currentIndex.value - 1].route)
}
</script>

<template>
  <div class="guide-layout">
    <header class="guide-bar">
      <router-link to="/" class="brand">CareerAgent</router-link>
      <div class="stage-pocket">
        <span class="stage-here">{{ headerText }}</span>
        <span v-if="nextText" class="stage-next">{{ nextText }}</span>
      </div>
      <div class="user-area">
        <router-link to="/chat" class="chat-link">AI 对话</router-link>
        <el-dropdown trigger="click">
          <span class="user-pill">{{ userStore.userInfo?.username || '我' }}</span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="userStore.logout()">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <GuideProgressBar :steps="GUIDE_STEPS" :current="currentStep" />

    <main class="guide-content">
      <router-view v-slot="{ Component, route: child }">
        <Transition name="page-slide" mode="out-in">
          <component :is="Component" :key="child.path" />
        </Transition>
      </router-view>
    </main>

    <nav class="guide-actions">
      <p v-if="journey.offline" class="offline-hint">离线缓存</p>
      <div class="action-btns">
        <el-button class="back-btn hover-lift" @click="back">上一步</el-button>
        <el-button type="primary" class="advance-btn hover-lift press-effect"
                   :disabled="!canAdvance" @click="advance">下一步</el-button>
      </div>
    </nav>
  </div>
</template>

<style scoped>
.guide-layout {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--c-bg);
}
.guide-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-8);
  border-bottom: 1px solid var(--c-bg-mute);
  background: var(--c-surface);
}
.brand {
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 600;
  color: var(--c-text-1);
  text-decoration: none;
  white-space: nowrap;
}
.stage-pocket {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.stage-here {
  font-size: 14px;
  font-weight: 600;
  color: var(--c-text-1);
}
.stage-next {
  font-size: 12px;
  color: var(--c-text-3);
}
.user-area {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}
.chat-link {
  font-size: 13px;
  color: var(--c-brand);
  text-decoration: none;
}
.user-pill {
  cursor: pointer;
  font-size: 13px;
  color: var(--c-text-1);
}
.guide-content {
  flex: 1;
  width: 100%;
  max-width: 720px;
  margin: 0 auto;
  padding: var(--space-12) var(--space-6) var(--space-8);
}
.guide-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  width: 100%;
  max-width: 720px;
  margin: 0 auto;
  padding: var(--space-4) var(--space-6) var(--space-8);
  border-top: 1px solid var(--c-bg-mute);
}
.action-btns {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-left: auto;
}
.offline-hint {
  font-size: 12px;
  color: var(--c-warning);
  margin: 0;
}
</style>
