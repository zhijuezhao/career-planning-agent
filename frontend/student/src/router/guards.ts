import type { Router } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getToken, TOKEN_KEY } from '../api/auth'
import type { GuideStep } from '../api/journey'
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

    // 3) 业务区路由的引导归位（R-12.1 守卫修复）：引导中的用户（zone=guide）
    //    不得绕过引导直接进业务区。
    //    必须排除 /chat：引导区顶栏「AI 对话」链向它（GuideLayout.vue:51），
    //    不排除则点击后被弹回引导区，形成重定向死循环。
    //    不加限制的情形：zone=welcome（欢迎页有「直接进入成果区」的显式逃生入口，
    //    且此阶段业务区尚无内容）、zone=business（已出报告，业务区是其正式主场）。
    if (token && !isGuideRoute(to.path) && to.path !== '/chat') {
      try {
        const store = useJourneyStore()
        if (store.zone === 'guide') {
          const back = guideRouteFor(store.guideStep)
          if (to.path !== back) { next({ path: back }); return }
        }
      } catch {
        /* 状态不可用时放行，绝不因归位失败卡死导航 */
      }
    }

    next()
  })
}

/** 是否属于引导区路由（/guide/*） */
function isGuideRoute(path: string): boolean {
  return path === '/guide' || path.startsWith('/guide/')
}

/** 引导步骤 → 对应引导区路由 */
function guideRouteFor(step: GuideStep | null): string {
  return GUIDE_STEP_MAP[step ?? 'resume'].route
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