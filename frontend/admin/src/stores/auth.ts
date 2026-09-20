import { defineStore } from 'pinia'
import { ref } from 'vue'

// 管理端独立 localStorage 键位：与学生端（token / username）隔离，
// 避免同源下两端登录互相串号（S2 修复）。
export const ADMIN_TOKEN_KEY = 'admin_token'
export const ADMIN_NAME_KEY = 'admin_username'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem(ADMIN_TOKEN_KEY) || '')
  const username = ref(localStorage.getItem(ADMIN_NAME_KEY) || '')

  const setToken = (newToken: string, name: string) => {
    token.value = newToken
    username.value = name
    localStorage.setItem(ADMIN_TOKEN_KEY, newToken)
    localStorage.setItem(ADMIN_NAME_KEY, name)
  }

  const clearToken = () => {
    token.value = ''
    username.value = ''
    localStorage.removeItem(ADMIN_TOKEN_KEY)
    localStorage.removeItem(ADMIN_NAME_KEY)
  }

  const isLoggedIn = () => !!token.value

  return { token, username, setToken, clearToken, isLoggedIn }
})