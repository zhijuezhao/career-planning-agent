import { defineStore } from 'pinia'
import { ref } from 'vue'
import { journeyApi, type GuideStep, type JourneyStatusResponse, type Zone } from '@/api/journey'

const CACHE_PREFIX = 'journey.v1.'
export const WELCOME_SEEN_KEY = 'journey.v1.welcome_seen'

function cacheKey(name: string) { return `${CACHE_PREFIX}${name}` }

export const useJourneyStore = defineStore('journey', () => {
  const zone = ref<Zone>('welcome')
  const guideStep = ref<GuideStep | null>(null)
  const snapshotId = ref<number | null>(null)
  const reportId = ref<number | null>(null)
  const reportVersions = ref(0)
  const offline = ref(false)
  const welcomeSeen = ref(localStorage.getItem(WELCOME_SEEN_KEY) === '1')

  function applyToCache(s: JourneyStatusResponse) {
    localStorage.setItem(cacheKey('zone'), s.zone)
    localStorage.setItem(cacheKey('status'), JSON.stringify(s))
  }
  function readFromCache(): JourneyStatusResponse | null {
    const raw = localStorage.getItem(cacheKey('status'))
    if (!raw) return null
    try {
      const s = JSON.parse(raw) as JourneyStatusResponse
      if (s && typeof s.zone === 'string') return s
      return null
    } catch { return null }
  }

  function applyCache(s: JourneyStatusResponse) {
    zone.value = s.zone
    guideStep.value = s.guide_step
    snapshotId.value = s.snapshot_id
    reportId.value = s.report_id
    reportVersions.value = s.report_versions
  }

  async function fetchStatus() {
    try {
      const res = await journeyApi.getStatus()
      zone.value = res.zone
      guideStep.value = res.guide_step
      snapshotId.value = res.snapshot_id
      reportId.value = res.report_id
      reportVersions.value = res.report_versions
      applyToCache(res)
      offline.value = false
    } catch (err: any) {
      if (err?.response?.status === 401) throw err
      const cached = readFromCache()
      if (cached) {
        applyCache(cached)      // 逐字段解构进 refs（readFromCache 已 parse + 校验 zone 字段）
        offline.value = true
      }
    }
  }

  function markWelcomeSeen() {
    welcomeSeen.value = true
    localStorage.setItem(WELCOME_SEEN_KEY, '1')
  }

  function setGuideStep(s: GuideStep) {
    guideStep.value = s          // 前端瞬时态，仅本地优先级高于服务端
  }

  function clearCache() {
    Object.keys(localStorage).filter(k => k.startsWith(CACHE_PREFIX)).forEach(k => localStorage.removeItem(k))
    welcomeSeen.value = false
  }

  return { zone, guideStep, snapshotId, reportId, reportVersions, offline, welcomeSeen,
           fetchStatus, setGuideStep, markWelcomeSeen, clearCache }
})