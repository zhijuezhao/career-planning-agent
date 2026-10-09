/**
 * 全局应用状态管理
 * 管理应用级别的共享状态：全局加载状态、侧边栏折叠、通知等
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useAppStore = defineStore('app', () => {
  // ==================== 状态 ====================

  /** 全局加载状态 */
  const globalLoading = ref(false)
  /** 加载提示文本 */
  const loadingText = ref('加载中...')
  /** 全局通知列表 */
  const notifications = ref<Array<{
    id: number
    type: 'success' | 'warning' | 'error' | 'info'
    message: string
    timestamp: number
  }>>([])
  /** 通知 ID 自增器 */
  let notificationId = 0

  // ==================== 计算属性 ====================

  /** 是否有未读通知（最近1小时内的） */
  const recentNotifications = computed(() => {
    const oneHourAgo = Date.now() - 3600000
    return notifications.value.filter(n => n.timestamp > oneHourAgo)
  })

  // ==================== 方法 ====================

  /** 设置全局加载状态 */
  function setGlobalLoading(loading: boolean, text?: string) {
    globalLoading.value = loading
    if (text) loadingText.value = text
  }

  /** 添加通知 */
  function addNotification(type: 'success' | 'warning' | 'error' | 'info', message: string) {
    const id = ++notificationId
    notifications.value.unshift({
      id,
      type,
      message,
      timestamp: Date.now(),
    })
    // 最多保留10条
    if (notifications.value.length > 10) {
      notifications.value = notifications.value.slice(0, 10)
    }
    return id
  }

  /** 移除通知 */
  function removeNotification(id: number) {
    const idx = notifications.value.findIndex(n => n.id === id)
    if (idx !== -1) notifications.value.splice(idx, 1)
  }

  /** 清空所有通知 */
  function clearNotifications() {
    notifications.value = []
  }

  return {
    globalLoading,
    loadingText,
    notifications,
    recentNotifications,
    setGlobalLoading,
    addNotification,
    removeNotification,
    clearNotifications,
  }
})
