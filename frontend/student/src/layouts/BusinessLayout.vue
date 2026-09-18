<script setup lang="ts">
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()
</script>

<template>
  <div class="business-layout">
    <header class="business-bar">
      <router-link to="/" class="brand">CareerAgent</router-link>
      <div class="user-area">
        <span class="user-pill">{{ userStore.userInfo?.username || '我' }}</span>
        <el-dropdown trigger="click">
          <span class="user-pill user-dropdown">▾</span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="userStore.logout()">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>
    <main class="business-content">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.business-layout {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--c-bg);
}
.business-bar {
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
.user-area {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}
.user-pill {
  font-size: 13px;
  color: var(--c-text-1);
}
.user-dropdown {
  cursor: pointer;
}
.business-content {
  flex: 1;
  width: 100%;
  max-width: 1200px;
  margin: 0 auto;
  padding: var(--space-6);
}
</style>