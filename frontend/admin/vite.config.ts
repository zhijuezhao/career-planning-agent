import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'
import path from 'node:path'

export default defineConfig({
  plugins: [vue()],
  base: '/admin/',
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    port: 5174,
    proxy: {
      // 后端以 Docker 运行：容器内 8001，宿主机映射 8002（见 docs/本地运行启动说明.md）
      // 若改用本地原生 uvicorn（--port 8001），临时改回 http://localhost:8001（改完不要提交）
      '/api': {
        target: 'http://localhost:8002',
        changeOrigin: true,
      },
    },
  },
})
