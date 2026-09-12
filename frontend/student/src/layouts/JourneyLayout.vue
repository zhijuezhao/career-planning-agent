<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { STAGE_META } from '@/constants/journey'
import type { JourneyStage } from '@/api/journey'
import { useJourneyStore } from '@/stores/journey'
import { useUserStore } from '@/stores/user'
import JourneyStepper from '@/components/JourneyStepper.vue'

const route = useRoute()
const journey = useJourneyStore()
const userStore = useUserStore()

const STAGE_KEYS: JourneyStage[] = ['upload', 'parsing', 'jobs', 'matching', 'career', 'report', 'done']

const currentStageKey = computed<JourneyStage>(() => {
  const s = route.meta.stage as JourneyStage | undefined
  return s ?? 'upload'
})
const currentIndex = computed(() => STAGE_META[currentStageKey.value].stepperIndex)

const stepperItems = computed(() =>
  STAGE_KEYS.map(key => ({
    label: STAGE_META[key].label,
    state: (STAGE_META[key].stepperIndex < currentIndex.value
      ? 'done'
      : STAGE_META[key].stepperIndex === currentIndex.value
        ? 'current'
        : 'locked') as 'done' | 'current' | 'locked',
  })),
)

const headerText = computed(() => {
  const s = route.meta.stage as JourneyStage | undefined
  if (!s) return 'AI 对话'          // /chat 等非阶段页
  return `我在 ${STAGE_META[s].title}`
})

const nextStageText = computed(() => {
  const s = route.meta.stage as JourneyStage | undefined
  if (!s) return ''
  const idx = STAGE_META[s].stepperIndex
  if (idx >= 7) return '旅程已完成'
  return `下一步：${STAGE_META[STAGE_KEYS[idx]].label}`
})

function canAdvance() {
  return false // 阶段 B 占位：无产出校验，始终禁用；阶段 C 逐步开闸
}

function handleAdvance() {
  if (!canAdvance()) return
}
</script>

<template>
  <div class="journey-layout">
    <header class="journey-bar">
      <router-link to="/dashboard" class="brand">CareerAgent</router-link>
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

    <nav class="journey-actions">
      <el-button
        type="primary"
        :disabled="!canAdvance()"
        class="advance-btn"
        @click="handleAdvance"
      >
        下一步
      </el-button>
    </nav>
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
.journey-actions {
  padding: var(--space-5) var(--space-8);
  display: flex;
  justify-content: center;
  border-top: 1px solid var(--c-bg-mute);
  background: var(--c-surface);
}
.advance-btn {
  min-width: 200px;
  height: 44px;
}
</style>