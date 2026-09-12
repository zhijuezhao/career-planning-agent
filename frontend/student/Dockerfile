FROM node:22-alpine AS builder

WORKDIR /app

COPY package.json .
RUN npm install --registry=https://registry.npmmirror.com

COPY . .
RUN npm run build

FROM alpine:3.19 AS export
COPY --from=builder /app/dist /dist
CMD ["sh", "-c", "echo 'Student frontend ready' && tail -f /dev/null"]
