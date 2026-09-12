import { defineStore } from 'pinia'
import { ref } from 'vue'
import { authApi, type UserInfo } from '../api/auth'

export const useUserStore = defineStore('user', () => {
  const token = ref(localStorage.getItem('access_token') || '')
  const userInfo = ref<UserInfo | null>(null)

  async function login(username: string, password: string) {
    const res = await authApi.login({ username, password })
    token.value = res.access_token
    localStorage.setItem('access_token', res.access_token)
    await fetchUserInfo()
  }

  async function register(username: string, password: string, email?: string) {
    await authApi.register({ username, password, email })
  }

  async function fetchUserInfo() {
    try {
      userInfo.value = await authApi.getMe()
    } catch {
      userInfo.value = null
    }
  }

  function logout() {
    token.value = ''
    userInfo.value = null
    localStorage.removeItem('access_token')
  }

  return { token, userInfo, login, register, fetchUserInfo, logout }
})
