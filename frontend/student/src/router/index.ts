import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import JourneyLayout from '../layouts/JourneyLayout.vue'
import { registerGuards } from './guards'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/home/LoginView.vue'),
    meta: { guestOnly: true, title: '登录' },
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('../views/home/RegisterView.vue'),
    meta: { guestOnly: true, title: '注册' },
  },
  {
    // 公共开场页：未登录可访问；已登录由守卫重定向到当前阶段
    path: '/start',
    name: 'Start',
    component: () => import('../views/journey/StartView.vue'),
    meta: { requiresAuth: false, title: '开始' },
  },
  {
    // 旅程父布局：7 个阶段页 + /chat 作为绝对路径子路由挂载
    path: '/',
    name: 'JourneyRoot',
    component: JourneyLayout,
    meta: { requiresAuth: true },
    children: [
      {
        path: '/upload',
        name: 'Upload',
        component: () => import('../views/journey/UploadView.vue'),
        meta: { stage: 'upload', title: '上传简历' },
      },
      {
        path: '/parsing',
        name: 'Parsing',
        component: () => import('../views/journey/ParsingView.vue'),
        meta: { stage: 'parsing', title: '画像解析' },
      },
      {
        path: '/jobs',
        name: 'Jobs',
        component: () => import('../views/journey/JobsView.vue'),
        meta: { stage: 'jobs', title: '选择岗位' },
      },
      {
        path: '/matching',
        name: 'Matching',
        component: () => import('../views/journey/MatchingView.vue'),
        meta: { stage: 'matching', title: '人岗匹配' },
      },
      {
        path: '/career',
        name: 'Career',
        component: () => import('../views/journey/CareerView.vue'),
        meta: { stage: 'career', title: '成长路线' },
      },
      {
        path: '/report',
        name: 'Report',
        component: () => import('../views/journey/ReportView.vue'),
        meta: { stage: 'report', title: '职业报告' },
      },
      {
        path: '/dashboard',
        name: 'Dashboard',
        component: () => import('../views/journey/DashboardView.vue'),
        meta: { stage: 'done', title: '成果总览' },
      },
      {
        path: '/chat',
        name: 'Chat',
        component: () => import('../views/chat/ChatView.vue'),
        meta: { title: 'AI 对话' },
      },
      // 根路径 → /start，由守卫接续处理
      { path: '', redirect: '/start' },
    ],
  },
  // 404 → /start，由守卫按登录态归位
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    redirect: '/start',
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(_to, _from, savedPosition) {
    if (savedPosition) return savedPosition
    return { top: 0 }
  },
})

registerGuards(router)

export default router