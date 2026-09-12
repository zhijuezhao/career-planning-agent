import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/home/LoginView.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('../views/home/RegisterView.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/',
    component: () => import('../layouts/DefaultLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        name: 'Home',
        component: () => import('../views/home/HomeView.vue'),
      },
      {
        path: 'chat',
        name: 'Chat',
        component: () => import('../views/chat/ChatView.vue'),
      },
      {
        path: 'profile',
        name: 'Profile',
        component: () => import('../views/profile/ProfileView.vue'),
      },
      {
        path: 'matching',
        name: 'Matching',
        component: () => import('../views/matching/MatchingView.vue'),
      },
      {
        path: 'career',
        name: 'Career',
        component: () => import('../views/career/CareerView.vue'),
      },
      {
        path: 'report',
        name: 'Report',
        component: () => import('../views/report/ReportView.vue'),
      },
      {
        path: 'jobs',
        name: 'Jobs',
        component: () => import('../views/jobs/JobsView.vue'),
      },
      {
        path: 'resume',
        name: 'Resume',
        component: () => import('../views/resume/ResumeView.vue'),
      },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  const token = localStorage.getItem('access_token')
  if (to.meta.requiresAuth !== false && !token) {
    return { name: 'Login' }
  }
})

export default router
