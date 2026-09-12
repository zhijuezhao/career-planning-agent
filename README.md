# 大学生职业规划智能体

> AI 驱动的职业规划平台，为大学生提供智能简历分析、岗位匹配、职业规划和成长计划服务。

[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.141-green)](https://fastapi.tiangolo.com)
[![Vue.js](https://img.shields.io/badge/Vue.js-3-42b883)](https://vuejs.org)
[![Tests](https://img.shields.io/badge/Tests-621_passed-brightgreen)]()
[![Coverage](https://img.shields.io/badge/Coverage-78%25-brightgreen)]()
[![License](https://img.shields.io/badge/License-MIT-yellow)]()

---

## ✨ 功能特性

### 🎯 学生端
- **智能简历解析** - PDF 简历上传，自动提取五层画像（基础信息、教育背景、工作经历、技能、项目经验）
- **人岗匹配** - 基于向量相似度 + 维度评分的智能匹配算法
- **职业规划** - AI 生成职业发展路线和成长计划
- **生涯报告** - 自动生成 Word 格式的职业规划报告
- **AI 对话** - 流式对话，支持 SSE 实时响应

### 🛠️ 管理端
- **仪表盘** - 用户统计、岗位分布、匹配数据可视化
- **岗位管理** - 岗位画像 CRUD、数据导入、批量操作
- **用户管理** - 用户列表、角色管理、状态控制
- **匹配管理** - 匹配结果查看、反馈管理、维度权重配置
- **系统配置** - AI 模型配置、调度器状态监控

### 🔧 技术特性
- **LangGraph Agent** - 基于状态图的 AI Agent 编排
- **RAG 知识库** - 向量检索增强生成
- **多模型支持** - DeepSeek / Qwen / LongCat 热切换
- **实时通信** - SSE 流式响应
- **容器化部署** - Docker Compose 一键部署

---

## 🏗️ 技术栈

### 后端
| 类别 | 技术 |
|------|------|
| 框架 | FastAPI + Uvicorn |
| AI/LLM | LangChain + LangGraph + LangSmith |
| 数据库 | PostgreSQL + pgvector |
| 缓存 | Redis |
| 认证 | JWT (python-jose) |
| 迁移 | Alembic |
| 日志 | Loguru |

### 前端
| 类别 | 技术 |
|------|------|
| 框架 | Vue 3 + TypeScript |
| UI 库 | Element Plus |
| 状态管理 | Pinia |
| 图表 | ECharts |
| 构建工具 | Vite |

---

## 📁 项目结构

```
career-planning-agent/
├── backend/                 # 后端代码
│   ├── app/
│   │   ├── api/             # API 路由层
│   │   ├── core/            # 核心业务逻辑
│   │   ├── domain/          # 领域模型和服务
│   │   ├── infrastructure/  # 基础设施
│   │   ├── schemas/         # 数据验证
│   │   └── utils/           # 工具函数
│   ├── tests/               # 测试
│   └── alembic/             # 数据库迁移
├── frontend/                # 前端代码
│   ├── admin/               # 管理后台
│   └── student/             # 学生端
├── nginx/                   # Nginx 配置
├── docker-compose.yml       # 开发环境
├── docker-compose.prod.yml  # 生产环境
└── docs/                    # 文档
```

---

## 🚀 快速开始

### 前置要求
- Python 3.12+
- Node.js 22+
- Docker & Docker Compose (推荐)

### 方式一：Docker 部署（推荐）

```bash
# 1. 克隆项目
git clone <repository-url>
cd career-planning-agent

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API Key

# 3. 启动服务
docker compose up -d

# 4. 访问
# 学生端: http://localhost
# 管理端: http://localhost/admin/
# API 文档: http://localhost/docs
```

### 方式二：本地开发

#### 后端
```bash
cd backend

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 运行迁移
alembic upgrade head

# 启动服务
python -m uvicorn app.main:app --reload --port 8001
```

#### 前端
```bash
# 学生端
cd frontend/student
npm install
npm run dev  # http://localhost:5173

# 管理端
cd frontend/admin
npm install
npm run dev  # http://localhost:5174
```

---

## 📖 API 文档

启动服务后访问：
- **Swagger UI**: http://localhost/docs
- **ReDoc**: http://localhost/redoc

详见 [API 文档](docs/API.md)

---

## 🧪 测试

```bash
# 运行全部测试
cd backend
python -m pytest tests/ -v

# 运行测试并生成覆盖率报告
python -m pytest tests/ --cov=app --cov-report=html
```

**测试统计**：
- 总测试数：621
- 覆盖率：78%
- 测试文件：58

---

## 🏭 生产部署

详见 [部署文档](docs/DEPLOYMENT.md)

```bash
# 1. 配置生产环境变量
cp .env.production.example .env
# 编辑 .env 填入真实值

# 2. 启动生产环境
docker compose -f docker-compose.prod.yml up -d --build
```

---

## 📊 核心模块

### Agent 引擎
- `core/agent/` - LangGraph Agent 基类和工具
- `core/resume_agent/` - 简历解析 Agent
- `core/job_agent/` - 岗位画像 Agent

### 匹配引擎
- `core/matching/job_matcher.py` - 人岗匹配算法
- `core/matching/path_planner.py` - 职业路线规划

### LLM 网关
- `core/llm/gateway.py` - 多模型网关
- `core/llm/models.py` - 供应商配置
- `core/llm/prompts/` - Prompt 模板

### RAG 模块
- `core/rag/indexer.py` - 向量索引
- `core/rag/retriever.py` - 向量检索

---

## 🔑 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `APP_ENV` | 环境 (development/production) | development |
| `DATABASE_URL` | 数据库连接 | postgresql+asyncpg://... |
| `REDIS_URL` | Redis 连接 | redis://localhost:6379/0 |
| `JWT_SECRET_KEY` | JWT 密钥 | (需设置) |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | (需设置) |
| `QWEN_API_KEY` | Qwen API Key | (需设置) |
| `SILICONFLOW_API_KEY` | SiliconFlow API Key | (需设置) |

详见 `.env.example`

---

## 🤝 贡献指南

1. Fork 项目
2. 创建功能分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送分支 (`git push origin feature/amazing-feature`)
5. 创建 Pull Request

---

## 📝 许可证

[MIT License](LICENSE)

---

## 📧 联系

如有问题，请提交 Issue 或联系项目维护者。

---

**版本**: v1.0.0 | **更新日期**: 2026-09-09
