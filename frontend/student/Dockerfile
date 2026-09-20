FROM node:22-alpine AS builder

WORKDIR /app

COPY package.json .
RUN npm install --registry=https://registry.npmmirror.com

COPY . .
RUN npm run build

FROM alpine:3.19 AS export
# ⚠️ 产物必须落在 compose 挂载的卷路径 `/app/dist`（docker-compose.yml:
#    student_frontend_dist:/app/dist）。原先 COPY 到 `/dist` 与挂载点不一致，
#    导致 volume 永远为空 → nginx 读不到 index.html，首页 403（2026-09-20 修复）。
COPY --from=builder /app/dist /app/dist
CMD ["sh", "-c", "echo 'Student frontend ready' && tail -f /dev/null"]
