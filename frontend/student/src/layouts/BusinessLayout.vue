<script setup lang="ts">
/**
 * 业务区外壳（layout-c 图标侧栏复刻，token 化 + 克制式）
 * - 侧栏 64px（--sidebar-width）：顶部品牌块 + 5 个图标导航（悬停出中文 tooltip）+ 底部用户区
 * - 主区：内容路由出口 + page-slide 转场
 * - 报告项带数字徽标（journey.reportVersions）→ 需在本层拉一次状态刷新
 */
import { onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useJourneyStore } from '@/stores/journey'
import {
  DataBoard,
  Document,
  Briefcase,
  Notebook,
  ChatDotRound,
} from '@element-plus/icons-vue'

interface NavItem {
  path: string
  label: string
  icon: typeof DataBoard
}

const NAV: NavItem[] = [
  { path: '/', label: '总览', icon: DataBoard },
  { path: '/resume', label: '我的简历', icon: Document },
  { path: '/jobs', label: '岗位库', icon: Briefcase },
  { path: '/career', label: '职业报告', icon: Notebook },
  { path: '/chat', label: 'AI 对话', icon: ChatDotRound },
]

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const journey = useJourneyStore()

/** 总览精确匹配，其余按前缀匹配（避免 '/' 命中所有路径） */
function isActive(p: string): boolean {
  return p === '/' ? route.path === '/' : route.path.startsWith(p)
}

/** 回到引导区（供用户重新走一遍引导） */
function goToGuide(): void {
  journey.setGuideStep('resume')
  router.push('/guide/resume')
}

onMounted(async () => {
  // 徽标依赖 reportVersions：本层主动拉一次（守卫只在 /welcome 与 guest 路由归位时会拉）
  try {
    await journey.fetchStatus()
  } catch {
    /* 离线/401 等：徽标降级不显示，不阻塞布局渲染 */
  }
})
</script>

<template>
  <div class="business-shell">
    <aside class="b-sidebar">
      <div
        class="b-brand hover-lift"
        role="button"
        tabindex="0"
        title="回到引导"
        @click="goToGuide"
        @keydown.enter="goToGuide"
      >
        C
      </div>

      <nav class="b-nav" aria-label="业务区导航">
        <router-link
          v-for="n in NAV"
          :key="n.path"
          :to="n.path"
          class="b-nav-item"
          :class="{ active: isActive(n.path) }"
        >
          <el-icon :size="18"><component :is="n.icon" /></el-icon>
          <span class="b-tip">{{ n.label }}</span>
          <span
            v-if="n.path === '/career' && journey.reportVersions > 0"
            class="b-badge"
          >{{ journey.reportVersions }}</span>
        </router-link>
      </nav>

      <div class="b-sidebar-footer">
        <el-dropdown trigger="click" placement="right-end">
          <span class="b-user" :title="userStore.userInfo?.username || '我'">
            {{ (userStore.userInfo?.username || '我').slice(0, 1).toUpperCase() }}
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item disabled>
                {{ userStore.userInfo?.username || '未登录' }}
              </el-dropdown-item>
              <el-dropdown-item @click="userStore.logout()">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </aside>

    <main class="b-main">
      <router-view v-slot="{ Component, route: child }">
        <Transition name="page-slide" mode="out-in">
          <component :is="Component" :key="child.path" />
        </Transition>
      </router-view>
    </main>
  </div>
</template>

<style scoped>
.business-shell {
  display: flex;
  min-height: 100vh;
  background: var(--c-bg);
}

/* ── 图标侧栏（layout-c：64px，白底，右侧 1px 分隔） ── */
.b-sidebar {
  flex: none;
  width: var(--sidebar-width);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-3) 0;
  background: var(--c-surface);
  border-right: 1px solid var(--c-bg-mute);
}
.b-brand {
  flex: none;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  background: var(--c-brand-gradient);
  color: #fff;
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 700;
  cursor: pointer;
  user-select: none;
}
.b-brand:focus-visible {
  outline: 2px solid var(--c-brand);
  outline-offset: 2px;
}

.b-nav {
  flex: 1;
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-1);
}
.b-nav-item {
  position: relative;
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  color: var(--c-text-3);
  text-decoration: none;
  transition: background var(--duration-fast) ease, color var(--duration-fast) ease;
}
.b-nav-item:hover {
  background: var(--c-bg-soft);
  color: var(--c-text-1);
}
.b-nav-item.active {
  background: var(--c-brand-lighter);
  color: var(--c-brand);
}

/* 悬停 tooltip（layout-c 的 .nav-tooltip） */
.b-tip {
  position: absolute;
  left: 56px;
  top: 50%;
  transform: translateY(-50%);
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--c-text-1);
  color: #fff;
  font-size: var(--text-xs);
  white-space: nowrap;
  opacity: 0;
  pointer-events: none;
  transition: opacity var(--duration-fast) ease;
  z-index: 10;
}
.b-nav-item:hover .b-tip {
  opacity: 1;
}

/* 报告版本徽标 */
.b-badge {
  position: absolute;
  top: 4px;
  right: 4px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-full);
  background: var(--c-danger);
  color: #fff;
  font-size: 10px;
  font-weight: 600;
  line-height: 1;
}

.b-sidebar-footer {
  flex: none;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 0 var(--space-2);
}
.b-user {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-full);
  background: var(--c-brand-gradient);
  color: #fff;
  font-size: var(--text-sm);
  font-weight: 600;
  cursor: pointer;
  user-select: none;
}

/* ── 主区 ── */
.b-main {
  flex: 1;
  min-width: 0;
  padding: var(--space-6);
}

@media (max-width: 768px) {
  .b-main {
    padding: var(--space-4);
  }
}
</style>
