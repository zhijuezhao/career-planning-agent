<script setup lang="ts">
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import {
  HomeFilled,
  ChatLineSquare,
  UserFilled,
  Opportunity,
  TrendCharts,
  Document,
  Search,
  Briefcase,
  Bell,
  Setting,
} from '@element-plus/icons-vue'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const menuItems = [
  { index: '/', icon: HomeFilled, label: '首页' },
  { index: '/chat', icon: ChatLineSquare, label: 'AI对话' },
  { index: '/profile', icon: UserFilled, label: '能力画像' },
  { index: '/matching', icon: Opportunity, label: '岗位匹配' },
  { index: '/career', icon: TrendCharts, label: '成长路径' },
  { index: '/report', icon: Document, label: '职业报告' },
  { index: '/jobs', icon: Search, label: '职位搜索' },
  { index: '/resume', icon: Briefcase, label: '简历管理' },
]

const username = computed(() => userStore.userInfo?.username || '用户')
const usernameInitial = computed(() => username.value.charAt(0))

const greetingText = computed(() => {
  const hour = new Date().getHours()
  if (hour >= 5 && hour < 12) return '早上好'
  if (hour >= 12 && hour < 18) return '下午好'
  if (hour >= 18 && hour < 23) return '晚上好'
  return '夜深了'
})

function isActive(index: string) {
  if (index === '/') return route.path === '/'
  return route.path.startsWith(index)
}

function handleLogout() {
  userStore.logout()
  router.push('/login')
}
</script>

<template>
  <div class="app-layout">
    <nav class="icon-sidebar">
      <div class="sidebar-logo">C</div>
      <div class="nav-items">
        <router-link
          v-for="item in menuItems"
          :key="item.index"
          :to="item.index"
          class="nav-item"
          :class="{ active: isActive(item.index) }"
        >
          <el-icon :size="20">
            <component :is="item.icon" />
          </el-icon>
          <span class="nav-tooltip">{{ item.label }}</span>
        </router-link>
      </div>
      <div class="nav-bottom">
        <div class="nav-item" @click="handleLogout">
          <el-icon :size="20"><Setting /></el-icon>
          <span class="nav-tooltip">设置 / 退出</span>
        </div>
      </div>
    </nav>

    <div class="main-area">
      <header class="status-bar">
        <div class="status-left">
          <div class="greeting-group">
            <h1 class="greeting">{{ greetingText }}，{{ username }}</h1>
            <span class="greeting-sub">你的AI职业规划助手已就绪</span>
          </div>
          <div class="quick-actions">
            <button class="quick-btn hover-lift press-effect" @click="$router.push('/chat')">
              <el-icon><ChatLineSquare /></el-icon>
              快速提问
            </button>
            <button class="quick-btn hover-lift press-effect" @click="$router.push('/resume')">
              <el-icon><Document /></el-icon>
              更新简历
            </button>
            <button class="quick-btn hover-lift press-effect" @click="$router.push('/jobs')">
              <el-icon><Search /></el-icon>
              搜索岗位
            </button>
          </div>
        </div>
        <div class="status-right">
          <div class="icon-btn notification-btn">
            <el-icon :size="18"><Bell /></el-icon>
            <span class="badge-dot"></span>
          </div>
          <el-dropdown trigger="click" @command="handleLogout">
            <div class="user-pill">
              <div class="user-pill-avatar">{{ usernameInitial }}</div>
              <span class="user-pill-name">{{ username }}</span>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <main class="dashboard-content">
        <router-view v-slot="{ Component, route: childRoute }">
          <Transition name="page-slide" mode="out-in">
            <component :is="Component" :key="childRoute.path" />
          </Transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<style scoped>
.app-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.icon-sidebar {
  width: var(--sidebar-width);
  background: var(--c-surface);
  border-right: 1px solid var(--c-bg-mute);
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: var(--space-3) 0;
  flex-shrink: 0;
  z-index: 10;
}

.sidebar-logo {
  width: 40px;
  height: 40px;
  background: var(--c-brand-gradient);
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 18px;
  font-weight: 700;
  margin-bottom: var(--space-6);
  cursor: pointer;
  transition: transform var(--duration-normal) var(--ease-spring);
}
.sidebar-logo:hover {
  transform: scale(1.08) rotate(-3deg);
}

.nav-items {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  width: 100%;
  padding: 0 var(--space-2);
  flex: 1;
}

.nav-item {
  width: 48px;
  height: 48px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--c-text-3);
  cursor: pointer;
  transition: all var(--duration-normal) var(--ease-out);
  position: relative;
  text-decoration: none;
}
.nav-item:hover {
  background: var(--c-bg-soft);
  color: var(--c-text-1);
}
.nav-item.active {
  background: var(--c-brand-lighter);
  color: var(--c-brand);
}

.nav-tooltip {
  position: absolute;
  left: 58px;
  background: var(--c-text-1);
  color: #fff;
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-sm);
  font-size: 12px;
  white-space: nowrap;
  opacity: 0;
  pointer-events: none;
  transition: opacity var(--duration-fast) ease, transform var(--duration-fast) var(--ease-out);
  transform: translateX(-4px);
  z-index: 100;
}
.nav-item:hover .nav-tooltip {
  opacity: 1;
  transform: translateX(0);
}

.nav-bottom {
  padding: 0 var(--space-2);
  margin-top: auto;
}

.main-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.status-bar {
  height: var(--header-height);
  background: var(--c-surface);
  border-bottom: 1px solid var(--c-bg-mute);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-8);
  flex-shrink: 0;
}

.status-left {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}

.greeting-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.greeting {
  font-size: 18px;
  font-weight: 600;
  color: var(--c-text-1);
}
.greeting-sub {
  font-size: 13px;
  color: var(--c-text-3);
}

.quick-actions {
  display: flex;
  gap: var(--space-2);
  margin-left: var(--space-6);
}

.quick-btn {
  padding: 6px 14px;
  border-radius: var(--radius-full);
  font-size: 13px;
  border: 1px solid var(--c-bg-mute);
  background: var(--c-surface);
  color: var(--c-text-2);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: all var(--duration-normal) var(--ease-out);
}
.quick-btn:hover {
  border-color: var(--c-brand);
  color: var(--c-brand);
  background: var(--c-brand-lighter);
}

.status-right {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}

.icon-btn {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background var(--duration-fast) ease;
  color: var(--c-text-2);
  position: relative;
}
.icon-btn:hover {
  background: var(--c-bg-soft);
}

.badge-dot {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 8px;
  height: 8px;
  background: var(--c-danger);
  border-radius: 50%;
  border: 2px solid var(--c-surface);
}
.badge-dot::after {
  content: '';
  position: absolute;
  inset: -2px;
  border-radius: 50%;
  background: var(--c-danger);
  animation: pulseRing 2s ease-out infinite;
}

.user-pill {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 4px 12px 4px 4px;
  border-radius: var(--radius-full);
  cursor: pointer;
  transition: background var(--duration-fast) ease;
}
.user-pill:hover {
  background: var(--c-bg-soft);
}

.user-pill-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--c-brand-gradient);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 500;
}

.user-pill-name {
  font-size: 13px;
  color: var(--c-text-1);
  font-weight: 500;
}

.dashboard-content {
  flex: 1;
  padding: var(--space-6) var(--space-8);
  overflow-y: auto;
  background: var(--c-bg);
}
</style>
