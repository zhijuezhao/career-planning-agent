import { createRouter, createWebHistory } from 'vue-router'
import AdminLayout from '@/layouts/AdminLayout.vue'
import { ADMIN_TOKEN_KEY } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: () => import('@/views/Login.vue'),
      meta: { title: '登录' },
    },
    {
      path: '/',
      component: AdminLayout,
      redirect: '/dashboard',
      children: [
        {
          path: 'dashboard',
          name: 'Dashboard',
          component: () => import('@/views/Dashboard.vue'),
          meta: { title: '仪表盘', icon: 'Odometer' },
        },
        {
          path: 'jobs',
          name: 'Jobs',
          component: () => import('@/views/Jobs.vue'),
          meta: { title: '岗位管理', icon: 'Briefcase' },
        },
        {
          path: 'raw-data',
          name: 'RawData',
          component: () => import('@/views/RawData.vue'),
          meta: { title: '原始数据', icon: 'Document' },
        },
        {
          path: 'import',
          name: 'Import',
          component: () => import('@/views/Import.vue'),
          meta: { title: '数据导入', icon: 'Upload' },
        },
        {
          path: 'matching',
          name: 'Matching',
          component: () => import('@/views/Matching.vue'),
          meta: { title: '匹配管理', icon: 'Connection' },
        },
        {
          path: 'career',
          name: 'Career',
          component: () => import('@/views/Career.vue'),
          meta: { title: '职业路线', icon: 'TrendCharts' },
        },
        {
          path: 'users',
          name: 'Users',
          component: () => import('@/views/Users.vue'),
          meta: { title: '用户管理', icon: 'User' },
        },
        {
          path: 'reports',
          name: 'Reports',
          component: () => import('@/views/Reports.vue'),
          meta: { title: '报告管理', icon: 'DocumentChecked' },
        },
        {
          path: 'chat',
          name: 'Chat',
          component: () => import('@/views/Chat.vue'),
          meta: { title: '对话记录', icon: 'ChatDotRound' },
        },
        {
          path: 'system',
          name: 'System',
          component: () => import('@/views/System.vue'),
          meta: { title: '系统配置', icon: 'Setting' },
        },
      ],
    },
    {
      // 兜底路由：任何未匹配路径都回仪表盘（避免刷新/手输路径时白屏，见 docs/superpowers/plans/2026-09-20-admin-console.md S0）
      path: '/:pathMatch(.*)*',
      name: 'NotFound',
      redirect: '/dashboard',
    },
  ],
})

// 守卫（S2）：除 /login 外都要求管理端 token；已登录时访问 /login 直接回仪表盘
router.beforeEach((to) => {
  const hasToken = !!localStorage.getItem(ADMIN_TOKEN_KEY)
  if (to.path === '/login') {
    return hasToken ? '/dashboard' : true
  }
  return hasToken ? true : '/login'
})

export default router
