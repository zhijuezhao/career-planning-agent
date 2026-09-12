import type { Router } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getToken, TOKEN_KEY } from '../api/auth'
import { STAGE_META } from '../constants/journey'
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

    // 2) 已登录访问 /login /register /start（招待归位）：按后端 stage 定位
    if (token && (guestOnly || to.path === '/start')) {
      await redirectToStage(next, token)
      return
    }

    next()
  })
}

async function redirectToStage(
  next: (arg?: unknown) => void,
  _token: string,
) {
  try {
    const store = useJourneyStore()
    await store.fetchStatus()
    const route = STAGE_META[store.stage]?.route ?? '/start'
    next({ path: route })
  } catch (err: any) {
    if (err?.response?.status === 401) {
      // token 失效：清空 token 与本地缓存，回登录页
      const store = useJourneyStore()
      store.clearCache()
      localStorage.removeItem(TOKEN_KEY)
      next({ path: '/login' })
      return
    }
    next({ path: '/start' })
  }
}