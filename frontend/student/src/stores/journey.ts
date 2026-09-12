import { defineStore } from 'pinia'
import { ref } from 'vue'
import { journeyApi, type JourneyStage, type JourneyStatusResponse } from '@/api/journey'

const CACHE_PREFIX = 'journey.v1.'

function cacheKey(name: string) {
  return `${CACHE_PREFIX}${name}`
}

export const useJourneyStore = defineStore('journey', () => {
  const stage = ref<JourneyStage>('start')
  const status = ref<JourneyStatusResponse | null>(null)
  const offline = ref(false)

  function applyToCache(s: JourneyStatusResponse) {
    localStorage.setItem(cacheKey('stage'), s.stage)
    localStorage.setItem(cacheKey('status'), JSON.stringify(s))
  }

  function readFromCache(): JourneyStatusResponse | null {
    const raw = localStorage.getItem(cacheKey('status'))
    if (!raw) return null
    try {
      const parsed = JSON.parse(raw) as JourneyStatusResponse
      if (!parsed || typeof parsed.stage !== 'string') return null
      return parsed
    } catch {
      return null
    }
  }

  async function fetchStatus() {
    try {
      const res = await journeyApi.getStatus()
      status.value = res
      stage.value = res.stage
      applyToCache(res)
      offline.value = false
    } catch (err: any) {
      // 401 抛给守卫按登出处理；其余失败降级缓存
      if (err?.response?.status === 401) throw err
      const cached = readFromCache()
      if (cached) {
        status.value = cached
        stage.value = cached.stage
        offline.value = true
      }
      // 无缓存：保持默认 '/start'，静默
    }
  }

  function setStage(s: JourneyStage, s2?: JourneyStatusResponse) {
    stage.value = s
    const next = s2 ?? ({ ...(status.value ?? {}), stage: s } as JourneyStatusResponse)
    status.value = next
    applyToCache(next)
  }

  function clearCache() {
    Object.keys(localStorage)
      .filter(k => k.startsWith(CACHE_PREFIX))
      .forEach(k => localStorage.removeItem(k))
  }

  return { stage, status, offline, fetchStatus, setStage, clearCache }
})