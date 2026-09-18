<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { ElMessage } from 'element-plus'

const router = useRouter()
const userStore = useUserStore()
const loading = ref(false)
const form = ref({ username: '', password: '', email: '' })
const shakeCard = ref(false)

async function handleRegister() {
  if (!form.value.username || !form.value.password) {
    ElMessage.warning('请输入用户名和密码')
    triggerShake()
    return
  }
  loading.value = true
  try {
    await userStore.register(form.value.username, form.value.password, form.value.email || undefined)
    ElMessage.success('注册成功，开始你的成长旅程')
    router.push('/welcome')
  } catch {
    triggerShake()
  } finally {
    loading.value = false
  }
}

function triggerShake() {
  shakeCard.value = true
  setTimeout(() => { shakeCard.value = false }, 500)
}
</script>

<template>
  <div class="auth-container">
    <div class="auth-card animate-scale-in" :class="{ shake: shakeCard }">
      <div class="auth-logo">C</div>
      <h2 class="auth-title">创建账号</h2>
      <p class="auth-subtitle">开始你的AI职业规划之旅</p>
      <el-form @submit.prevent="handleRegister" class="auth-form">
        <el-form-item>
          <el-input v-model="form.username" placeholder="用户名 *" prefix-icon="User" size="large" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="form.email" placeholder="邮箱（选填）" prefix-icon="Message" size="large" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="form.password" type="password" placeholder="密码 *" prefix-icon="Lock" size="large" show-password />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" size="large" :loading="loading" class="auth-submit hover-lift press-effect" native-type="submit">
            注册
          </el-button>
        </el-form-item>
      </el-form>
      <div class="auth-footer">
        已有账号？<router-link to="/login">去登录</router-link>
      </div>
    </div>
  </div>
</template>

<style scoped>
.auth-container {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100vh;
  background: var(--c-bg);
  position: relative;
  overflow: hidden;
}
.auth-container::before {
  content: '';
  position: absolute;
  width: 600px;
  height: 600px;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.08), transparent 70%);
  top: -200px;
  right: -100px;
  border-radius: 50%;
}
.auth-container::after {
  content: '';
  position: absolute;
  width: 400px;
  height: 400px;
  background: radial-gradient(circle, rgba(139, 92, 246, 0.06), transparent 70%);
  bottom: -100px;
  left: -50px;
  border-radius: 50%;
}
.auth-card {
  width: 420px;
  background: var(--c-surface);
  border-radius: var(--radius-lg);
  padding: var(--space-8);
  box-shadow: var(--shadow-lg);
  border: 1px solid var(--c-bg-mute);
  position: relative;
  z-index: 1;
}
.auth-logo {
  width: 48px;
  height: 48px;
  background: var(--c-brand-gradient);
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 22px;
  font-weight: 700;
  margin: 0 auto var(--space-4);
}
.auth-title {
  text-align: center;
  font-size: 24px;
  font-weight: 700;
  color: var(--c-text-1);
}
.auth-subtitle {
  text-align: center;
  font-size: 14px;
  color: var(--c-text-3);
  margin-top: var(--space-2);
  margin-bottom: var(--space-6);
}
.auth-form :deep(.el-input__wrapper) {
  border-radius: var(--radius-sm);
  transition: box-shadow var(--duration-fast) ease;
}
.auth-form :deep(.el-input__wrapper:focus-within) {
  box-shadow: 0 0 0 2px var(--c-brand-lighter);
}
.auth-submit {
  width: 100%;
  border-radius: var(--radius-sm);
  font-size: 15px;
  font-weight: 500;
  height: 44px;
}
.auth-footer {
  text-align: center;
  font-size: 14px;
  color: var(--c-text-3);
  margin-top: var(--space-4);
}
.auth-footer a {
  color: var(--c-brand);
  text-decoration: none;
  font-weight: 500;
  transition: opacity var(--duration-fast) ease;
}
.auth-footer a:hover {
  opacity: 0.8;
}
</style>