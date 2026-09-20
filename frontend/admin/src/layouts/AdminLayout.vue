<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import {
  ArrowDown,
  Briefcase,
  ChatDotRound,
  Connection,
  Document,
  DocumentChecked,
  Expand,
  Fold,
  Odometer,
  Setting,
  TrendCharts,
  Upload,
  User,
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const isCollapse = ref(false)
const authStore = useAuthStore()

const menuItems = [
  { path: '/dashboard', title: '仪表盘', icon: Odometer },
  { path: '/jobs', title: '岗位管理', icon: Briefcase },
  { path: '/raw-data', title: '原始数据', icon: Document },
  { path: '/import', title: '数据导入', icon: Upload },
  { path: '/matching', title: '匹配管理', icon: Connection },
  { path: '/career', title: '职业路线', icon: TrendCharts },
  { path: '/users', title: '用户管理', icon: User },
  { path: '/reports', title: '报告管理', icon: DocumentChecked },
  { path: '/chat', title: '对话记录', icon: ChatDotRound },
  { path: '/system', title: '系统配置', icon: Setting },
]

const currentPath = computed(() => route.path)

const handleLogout = async () => {
  try {
    await ElMessageBox.confirm('确定要退出登录吗？', '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    })
    authStore.clearToken()
    router.push('/login')
  } catch {
    // cancelled
  }
}
</script>

<template>
  <el-container class="admin-container">
    <el-aside :width="isCollapse ? '64px' : '220px'" class="admin-aside">
      <div class="logo">
        <div class="logo-icon">
          <el-icon><Odometer /></el-icon>
        </div>
        <span v-if="!isCollapse" class="logo-text">管理后台</span>
      </div>
      <el-menu
        :default-active="currentPath"
        :collapse="isCollapse"
        router
        class="admin-menu"
      >
        <el-menu-item v-for="item in menuItems" :key="item.path" :index="item.path">
          <el-icon>
            <component :is="item.icon" />
          </el-icon>
          <template #title>{{ item.title }}</template>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="admin-header">
        <div class="header-left">
          <el-button class="collapse-btn" text @click="isCollapse = !isCollapse">
            <el-icon size="20">
              <Fold v-if="!isCollapse" />
              <Expand v-else />
            </el-icon>
          </el-button>
          <el-breadcrumb separator="/">
            <el-breadcrumb-item :to="{ path: '/dashboard' }">首页</el-breadcrumb-item>
            <el-breadcrumb-item>{{ route.meta.title || '页面' }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <div class="header-right">
          <el-dropdown @command="handleLogout">
            <span class="user-info">
              <el-avatar :size="32" class="user-avatar">
                <el-icon><User /></el-icon>
              </el-avatar>
              <span class="user-name">{{ authStore.username || '管理员' }}</span>
              <el-icon><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>
      <el-main class="admin-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.admin-container {
  height: 100vh;
}

.admin-aside {
  background-color: #fff;
  border-right: 1px solid #e6e6e6;
  transition: width 0.3s;
  overflow: hidden;
}

.logo {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  border-bottom: 1px solid #e6e6e6;
}

.logo-icon {
  width: 32px;
  height: 32px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 18px;
}

.logo-text {
  font-size: 16px;
  font-weight: 600;
  color: #1f2937;
  letter-spacing: 1px;
}

.admin-menu {
  border-right: none;
}

.admin-menu:not(.el-menu--collapse) {
  width: 220px;
}

.admin-menu .el-menu-item {
  height: 48px;
  line-height: 48px;
  margin: 4px 8px;
  border-radius: 8px;
  color: #606266;
}

.admin-menu .el-menu-item:hover {
  background-color: #f5f7fa;
  color: #667eea;
}

.admin-menu .el-menu-item.is-active {
  background-color: #eef2ff;
  color: #667eea;
  font-weight: 500;
}

.admin-header {
  background-color: #fff;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  border-bottom: 1px solid #e6e6e6;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.collapse-btn {
  padding: 8px;
  color: #606266;
}

.collapse-btn:hover {
  color: #667eea;
  background-color: #f5f7fa;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 8px;
  transition: background-color 0.2s;
}

.user-info:hover {
  background-color: #f5f7fa;
}

.user-avatar {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
}

.user-name {
  font-size: 14px;
  color: #606266;
}

.admin-main {
  background-color: #f5f7fa;
  padding: 20px;
}
</style>
