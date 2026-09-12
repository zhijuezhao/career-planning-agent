# 部署文档

> 大学生职业规划智能体 - 生产环境部署指南

---

## 📋 目录

- [系统要求](#系统要求)
- [快速部署](#快速部署)
- [手动部署](#手动部署)
- [SSL 配置](#ssl-配置)
- [数据库备份](#数据库备份)
- [监控与日志](#监控与日志)
- [故障排除](#故障排除)

---

## 系统要求

### 最低配置
| 资源 | 要求 |
|------|------|
| CPU | 2 核 |
| 内存 | 4 GB |
| 磁盘 | 20 GB |
| 网络 | 公网 IP (如需外部访问) |

### 推荐配置
| 资源 | 要求 |
|------|------|
| CPU | 4 核 |
| 内存 | 8 GB |
| 磁盘 | 50 GB SSD |
| 网络 | 公网 IP + 域名 |

### 软件依赖
- Docker 24.0+
- Docker Compose 2.20+

---

## 快速部署

### 1. 准备环境

```bash
# 克隆项目
git clone <repository-url>
cd career-planning-agent
```

### 2. 配置环境变量

```bash
# 复制生产环境变量模板
cp .env.production.example .env

# 编辑 .env 填入真实值
nano .env  # 或使用其他编辑器
```

**必须配置的环境变量**：

```env
# 数据库密码（必须设置强密码）
POSTGRES_PASSWORD=your_strong_password_here

# Redis 密码
REDIS_PASSWORD=your_redis_password_here

# JWT 密钥（生成：openssl rand -hex 32）
JWT_SECRET_KEY=your_generated_secret_key

# LLM API Keys
DEEPSEEK_API_KEY=sk-your-deepseek-key
QWEN_API_KEY=sk-your-qwen-key
SILICONFLOW_API_KEY=sk-your-siliconflow-key
```

### 3. 启动服务

```bash
# 构建并启动
docker compose -f docker-compose.prod.yml up -d --build

# 查看启动状态
docker compose -f docker-compose.prod.yml ps

# 查看日志
docker compose -f docker-compose.prod.yml logs -f
```

### 4. 验证部署

```bash
# 健康检查
curl http://localhost/health

# 访问服务
# 学生端: http://localhost
# 管理端: http://localhost/admin/
```

---

## 手动部署

### 目录结构准备

```bash
mkdir -p /opt/career-planning-agent
cd /opt/career-planning-agent

# 创建必要目录
mkdir -p nginx/ssl
mkdir -p backups
mkdir -p logs
```

### 配置文件

1. 复制项目文件到服务器
2. 配置 `.env` 文件
3. 放置 SSL 证书到 `nginx/ssl/`

### 启动命令

```bash
# 构建镜像
docker compose -f docker-compose.prod.yml build

# 启动服务
docker compose -f docker-compose.prod.yml up -d

# 查看状态
docker compose -f docker-compose.prod.yml ps -a
```

---

## SSL 配置

### 使用 Let's Encrypt (推荐)

```bash
# 安装 certbot
sudo apt install certbot

# 获取证书
sudo certbot certonly --standalone -d yourdomain.com

# 复制证书到项目目录
sudo cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem nginx/ssl/
sudo cp /etc/letsencrypt/live/yourdomain.com/privkey.pem nginx/ssl/

# 重启 nginx
docker compose -f docker-compose.prod.yml restart nginx
```

### 使用自有证书

```bash
# 将证书放置到 nginx/ssl/ 目录
# fullchain.pem - 证书链
# privkey.pem  - 私钥
```

### 自动续期 (Let's Encrypt)

```bash
# 添加 crontab
0 0 1 * * certbot renew --quiet && cp /etc/letsencrypt/live/yourdomain.com/*.pem /opt/career-planning-agent/nginx/ssl/ && docker compose -f /opt/career-planning-agent/docker-compose.prod.yml restart nginx
```

---

## 数据库备份

### 手动备份

```bash
# 进入 postgres 容器执行备份
docker exec career_postgres pg_dump -U postgres career_planning > backup_$(date +%Y%m%d_%H%M%S).sql
```

### 自动备份

取消 `docker-compose.prod.yml` 中 `db-backup` 服务的注释：

```yaml
db-backup:
  image: pgvector/pgvector:pg17
  container_name: career_db_backup
  restart: unless-stopped
  environment:
    POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
  volumes:
    - ./backups:/backups
  command: >
    sh -c "while true; do
      pg_dump -U postgres -h postgres career_planning > /backups/backup_$$(date +%Y%m%d_%H%M%S).sql;
      find /backups -name '*.sql' -mtime +7 -delete;
      sleep 86400;
    done"
  depends_on:
    postgres:
      condition: service_healthy
  networks:
    - backend_network
```

### 恢复备份

```bash
# 恢复指定备份文件
cat backup_20260909.sql | docker exec -i career_postgres psql -U postgres -d career_planning
```

---

## 监控与日志

### 查看日志

```bash
# 查看所有服务日志
docker compose -f docker-compose.prod.yml logs -f

# 查看特定服务日志
docker compose -f docker-compose.prod.yml logs -f backend
docker compose -f docker-compose.prod.yml logs -f nginx

# 查看最近 100 行日志
docker compose -f docker-compose.prod.yml logs --tail=100
```

### 容器状态

```bash
# 查看所有容器状态
docker compose -f docker-compose.prod.yml ps

# 查看资源使用
docker stats
```

### 健康检查

```bash
# 后端健康检查
curl http://localhost/health

# 数据库健康检查
docker exec career_postgres pg_isready -U postgres

# Redis 健康检查
docker exec career_redis redis-cli -a your_password ping
```

---

## 故障排除

### 常见问题

#### 1. 服务无法启动

```bash
# 检查日志
docker compose -f docker-compose.prod.yml logs

# 检查环境变量
docker compose -f docker-compose.prod.yml config

# 检查端口占用
netstat -tlnp | grep -E '80|443|5432|6379'
```

#### 2. 数据库连接失败

```bash
# 检查数据库状态
docker exec career_postgres pg_isready -U postgres

# 检查网络
docker network inspect career-planning-agent_backend_network
```

#### 3. 前端无法访问

```bash
# 检查 nginx 配置
docker exec career_nginx nginx -t

# 检查前端构建产物
docker exec career_nginx ls -la /usr/share/nginx/html/student
```

#### 502 Bad Gateway

```bash
# 检查后端是否运行
docker compose -f docker-compose.prod.yml ps backend

# 检查后端日志
docker compose -f docker-compose.prod.yml logs backend
```

### 重启服务

```bash
# 重启所有服务
docker compose -f docker-compose.prod.yml restart

# 重启单个服务
docker compose -f docker-compose.prod.yml restart backend
```

### 更新部署

```bash
# 拉取最新代码
git pull

# 重新构建并启动
docker compose -f docker-compose.prod.yml up -d --build

# 清理旧镜像
docker image prune -f
```

---

## 安全建议

### 1. 网络安全
- 使用防火墙限制端口访问
- 仅开放 80/443 端口
- 使用 VPN 或内网访问管理接口

### 2. 密码安全
- 使用强密码（16+ 字符）
- 定期更换密码
- 不同服务使用不同密码

### 3. 数据安全
- 定期备份数据库
- 使用 SSL/TLS 加密传输
- 限制数据库外部访问

### 4. 应用安全
- 及时更新依赖
- 启用日志审计
- 配置 fail2ban 防止暴力破解

---

## 性能优化

### 数据库优化
```sql
-- 定期清理过期数据
DELETE FROM chat_messages WHERE created_at < NOW() - INTERVAL '90 days';

-- 分析表
ANALYZE;
```

### Nginx 优化
- 已启用 Gzip 压缩
- 已配置静态资源缓存
- 支持 HTTP/2

### 应用优化
- 后端使用 4 worker 进程
- 数据库连接池配置
- Redis 缓存热点数据

---

**版本**: v1.0.0 | **更新日期**: 2026-09-09
