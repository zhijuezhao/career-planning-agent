import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('token') || '')
  const username = ref(localStorage.getItem('username') || '')

  const setToken = (newToken: string, name: string) => {
    token.value = newToken
    username.value = name
    localStorage.setItem('token', newToken)
    localStorage.setItem('username', name)
  }

  const clearToken = () => {
    token.value = ''
    username.value = ''
    localStorage.removeItem('token')
    localStorage.removeItem('username')
  }

  const isLoggedIn = () => !!token.value

  return { token, username, setToken, clearToken, isLoggedIn }
})
