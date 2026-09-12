import { defineStore } from 'pinia'
import { ref } from 'vue'
import { authApi, getToken, setToken, TOKEN_KEY, type UserInfo } from '../api/auth'

export const useUserStore = defineStore('user', () => {
  const token = ref(getToken())
  const userInfo = ref<UserInfo | null>(null)

  async function login(username: string, password: string) {
    const res = await authApi.login({ username, password })
    token.value = res.access_token
    setToken(res.access_token)
    await fetchUserInfo()
  }

  async function register(username: string, password: string, email?: string) {
    const user = await authApi.register({ username, password, email })
    // 注册接口不签发 token，需再用凭据换取；userInfo 用注册返回体兜底
    const res = await authApi.login({ username, password })
    token.value = res.access_token
    setToken(res.access_token)
    userInfo.value = user
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
    if (getToken()) localStorage.removeItem(TOKEN_KEY)
  }

  return { token, userInfo, login, register, fetchUserInfo, logout }
})
