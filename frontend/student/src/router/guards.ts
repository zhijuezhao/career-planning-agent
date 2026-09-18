import type { Router } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getToken, TOKEN_KEY } from '../api/auth'
import { GUIDE_STEP_MAP, GUIDE_STEPS } from '../constants/journey'
import { useJourneyStore } from '../stores/journey'

export function registerGuards(router: Router) {
  router.beforeEach(async (to, _from, next) => {
    const token = getToken()

    // 页面标题（沿用既有约定）
    const title = to.meta.title as string | undefined
    document.title = title ? `${title} - CareerAgent` : 'CareerAgent - 大学生职业规划智能体'

    const requiresAuth = to.matched.some(r => r.meta.requiresAuth === true)
    const guestOnly = to.matched.some(r => r.meta.guestOnly === true)

    // 1) 需登录但未登录 → 登录页并带回跳
    if (requiresAuth && !token) {
      ElMessage.warning('请先登录')
      next({ path: '/login', query: { redirect: to.fullPath } })
      return
    }

    // 2) 已登录访问 /login /register /welcome（招待归位）：两级决策
    if (token && (guestOnly || to.path === '/welcome')) {
      await redirectToZone(next, to)
      return
    }

    next()
  })
}

async function redirectToZone(next: (arg?: unknown) => void, to: { path: string }) {
  try {
    const store = useJourneyStore()
    await store.fetchStatus()
    // 第一级：未看过欢迎页 → /welcome（本地瞬时态，无需请求后端）
    if (!store.welcomeSeen) {
      if (to.path === '/welcome') { next(); return }
      next({ path: '/welcome' })
      return
    }
    // 第二级：看过欢迎页 → 按后端 zone/guideStep 归位
    const route = resolveZoneRoute()
    if (route === to.path) { next(); return }
    next({ path: route })
  } catch (err: any) {
    if (err?.response?.status === 401) {
      // token 失效：清空缓存与 token，回登录页
      const store = useJourneyStore()
      store.clearCache()
      localStorage.removeItem(TOKEN_KEY)
      next({ path: '/login' })
      return
    }
    // 服务端不可达：读本地缓存（fetchStatus 已自动读），回欢迎页兜底
    next({ path: '/welcome' })
  }
}

function resolveZoneRoute(): string {
  const store = useJourneyStore()
  if (store.zone === 'business') return '/'
  if (store.zone === 'guide') return GUIDE_STEP_MAP[store.guideStep ?? 'resume'].route
  return GUIDE_STEPS[0].route
}