import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { registerGuards } from './guards'

const routes: RouteRecordRaw[] = [
  { path: '/login', name: 'Login', component: () => import('../views/home/LoginView.vue'), meta: { guestOnly: true, title: '登录' } },
  { path: '/register', name: 'Register', component: () => import('../views/home/RegisterView.vue'), meta: { guestOnly: true, title: '注册' } },
  { path: '/welcome', name: 'Welcome', component: () => import('../views/welcome/WelcomeView.vue'), meta: { requiresAuth: false, title: '欢迎' } },

  // 引导区（5 步，Guide 外壳）
  {
    path: '/guide',
    component: () => import('../layouts/GuideLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      { path: 'resume', name: 'GuideResume', component: () => import('../views/guide/GuideResumeView.vue'), meta: { guide: 'resume', title: '上传简历' } },
      { path: 'parse', name: 'GuideParse', component: () => import('../views/guide/GuideParseView.vue'), meta: { guide: 'parse', title: '画像解析' } },
      { path: 'match', name: 'GuideMatch', component: () => import('../views/guide/GuideMatchView.vue'), meta: { guide: 'match', title: '选择岗位' } },
      { path: 'career', name: 'GuideCareer', component: () => import('../views/guide/GuideCareerView.vue'), meta: { guide: 'career', title: '匹配策略' } },
      { path: 'done', name: 'GuideDone', component: () => import('../views/guide/GuideDoneView.vue'), meta: { guide: 'done', title: '生成报告' } },
      { path: '', redirect: '/guide/resume' },
    ],
  },

  // 业务区（Task 12 建壳，BusinessLayout 父；页面 13-15 填）
  {
    path: '/',
    component: () => import('../layouts/BusinessLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      { path: '', name: 'Dashboard', component: () => import('../views/business/DashboardView.vue'), meta: { title: '总览' } },
      { path: 'resume', name: 'Resume', component: () => import('../views/business/ResumeView.vue'), meta: { title: '我的简历' } },
      { path: 'jobs', name: 'Jobs', component: () => import('../views/business/JobsView.vue'), meta: { title: '岗位库' } },
      { path: 'career', name: 'CareerReport', component: () => import('../views/business/CareerView.vue'), meta: { title: '职业报告' } },
      { path: 'chat', name: 'Chat', component: () => import('../views/business/ChatView.vue'), meta: { title: 'AI 对话' } },
    ],
  },

  { path: '/:pathMatch(.*)*', name: 'NotFound', redirect: '/welcome' },
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