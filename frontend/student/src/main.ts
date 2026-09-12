import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import '@/styles/variables.css'
import 'element-plus/dist/index.css'
import '@/styles/transitions.css'
import '@/styles/global.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import { createPinia } from 'pinia'
import router from './router'
import App from './App.vue'

const app = createApp(App)

for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(createPinia())
app.use(router)
app.use(ElementPlus)
app.mount('#app')
