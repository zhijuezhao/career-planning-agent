<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { GUIDE_STEP_MAP, GUIDE_STEPS } from '@/constants/journey'
import type { GuideStep } from '@/api/journey'
import { useJourneyStore } from '@/stores/journey'
import { useUserStore } from '@/stores/user'
import JourneyStepper from '@/components/JourneyStepper.vue'

const route = useRoute()
const journey = useJourneyStore()
const userStore = useUserStore()

const STAGE_KEYS: GuideStep[] = ['resume', 'parse', 'match', 'career', 'done']

const currentStageKey = computed<GuideStep>(() => {
  const s = route.meta.guide as GuideStep | undefined
  return s ?? 'resume'
})
const currentIndex = computed(() => GUIDE_STEP_MAP[currentStageKey.value].stepperIndex)

const stepperItems = computed(() =>
  STAGE_KEYS.map(key => ({
    label: GUIDE_STEP_MAP[key].label,
    state: (GUIDE_STEP_MAP[key].stepperIndex < currentIndex.value
      ? 'done'
      : GUIDE_STEP_MAP[key].stepperIndex === currentIndex.value
        ? 'current'
        : 'locked') as 'done' | 'current' | 'locked',
  })),
)

const headerText = computed(() => `我在 ${GUIDE_STEP_MAP[currentStageKey.value].title}`)

const nextStageText = computed(() => {
  const idx = GUIDE_STEP_MAP[currentStageKey.value].stepperIndex
  if (idx >= GUIDE_STEPS.length - 1) return '引导已完成'
  return `下一步：${GUIDE_STEPS[idx + 1].label}`
})
</script>

<template>
  <div class="journey-layout">
    <header class="journey-bar">
      <router-link to="/" class="brand">CareerAgent</router-link>
      <div class="stage-pocket">
        <span class="stage-here">{{ headerText }}</span>
        <span v-if="nextStageText" class="stage-next">{{ nextStageText }}</span>
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

    <JourneyStepper :items="stepperItems" />

    <main class="journey-content">
      <router-view v-slot="{ Component, route: childRoute }">
        <Transition name="page-slide" mode="out-in">
          <component :is="Component" :key="childRoute.path" />
        </Transition>
      </router-view>
      <p v-if="journey.offline" class="offline-hint">离线缓存</p>
    </main>
  </div>
</template>

<style scoped>
.journey-layout {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--c-bg);
}
.journey-bar {
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
.journey-content {
  flex: 1;
  width: 100%;
  max-width: 720px;
  margin: 0 auto;
  padding: var(--space-12) var(--space-6) var(--space-8);
}
.offline-hint {
  text-align: center;
  font-size: 12px;
  color: var(--c-warning);
  margin-top: var(--space-4);
}
</style>