# API 文档

> 大学生职业规划智能体 - RESTful API 接口文档

**Base URL**: `/api/v1`

**认证方式**: Bearer Token (JWT)

---

## 📋 目录

- [认证接口](#认证接口)
- [用户接口](#用户接口)
- [简历接口](#简历接口)
- [职业规划接口](#职业规划接口)
- [人岗匹配接口](#人岗匹配接口)
- [报告接口](#报告接口)
- [聊天接口](#聊天接口)
- [管理后台接口](#管理后台接口)

---

## 认证接口

### 注册
```
POST /api/v1/auth/register
```

**请求体**:
```json
{
  "username": "string",   // 3-50 字符
  "password": "string",   // 6-128 字符
  "email": "string",      // 可选
  "phone": "string"       // 可选，最大 20 字符
}
```

**响应**:
```json
{
  "id": 1,
  "username": "testuser",
  "email": "test@example.com",
  "role": "student",
  "status": 1,
  "created_at": "2026-09-09T10:00:00"
}
```

### 登录
```
POST /api/v1/auth/login
```

**请求体**:
```json
{
  "username": "string",
  "password": "string"
}
```

**响应**:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer"
}
```

---

## 用户接口

### 获取当前用户信息
```
GET /api/v1/users/me
```

**请求头**: `Authorization: Bearer <token>`

**响应**:
```json
{
  "id": 1,
  "username": "testuser",
  "email": "test@example.com",
  "role": "student",
  "status": 1,
  "created_at": "2026-09-09T10:00:00"
}
```

### 更新用户信息
```
PUT /api/v1/users/me
```

**请求体**:
```json
{
  "email": "new@example.com",
  "phone": "13800138000"
}
```

---

## 简历接口

### 上传简历
```
POST /api/v1/resume/upload
```

**请求头**: `Authorization: Bearer <token>`

**请求体**: `multipart/form-data`
- `file`: PDF 文件

**响应**:
```json
{
  "resume_id": 1,
  "status": "processing",
  "message": "简历上传成功，正在解析中..."
}
```

### 获取简历状态
```
GET /api/v1/resume/{resume_id}/status
```

**响应**:
```json
{
  "resume_id": 1,
  "status": "completed",
  "profile_id": 1,
  "error_message": null
}
```

### 获取简历详情
```
GET /api/v1/resume/{resume_id}
```

**响应**:
```json
{
  "resume_id": 1,
  "file_name": "resume.pdf",
  "status": "completed",
  "parsed_data": { ... },
  "profile_id": 1
}
```

---

## 职业规划接口

### 生成职业路线
```
POST /api/v1/career/path
```

**请求体**:
```json
{
  "profile_id": 1,
  "target_job_id": 1,
  "current_stage": "在校学生"
}
```

**响应**:
```json
{
  "id": 1,
  "user_id": 1,
  "target_position": "软件工程师",
  "path_type": "技术路线",
  "milestones": [ ... ],
  "learning_resources": { ... }
}
```

### 生成成长计划
```
POST /api/v1/career/growth-plan
```

**请求体**:
```json
{
  "growth_path_id": 1,
  "weekly_hours": 10,
  "cycle_weeks": 12
}
```

---

## 人岗匹配接口

### 执行匹配
```
POST /api/v1/matching/run
```

**请求体**:
```json
{
  "profile_id": 1,
  "top_k": 10,
  "max_distance": 0.5
}
```

**响应**:
```json
{
  "user_id": 1,
  "profile_id": 1,
  "total": 5,
  "results": [
    {
      "job_profile_id": 1,
      "match_score": 0.85,
      "distance": 0.15,
      "analysis": {
        "vector_similarity": 0.9,
        "dimension_score": 0.8,
        "dimension_matches": { ... }
      }
    }
  ]
}
```

### 提交反馈
```
POST /api/v1/matching/feedback
```

**请求体**:
```json
{
  "match_id": 1,
  "feedback_type": "like",  // like | dislike | applied | saved
  "comment": "这个岗位很适合我"
}
```

---

## 报告接口

### 生成报告
```
POST /api/v1/reports/generate
```

**请求体**:
```json
{
  "profile_id": 1,
  "target_job": "软件工程师"
}
```

**响应**:
```json
{
  "report_id": 1,
  "profile_id": 1,
  "target_job": "软件工程师",
  "report_content": { ... },
  "version": 1
}
```

### 下载报告
```
GET /api/v1/reports/{report_id}/download
```

**响应**:
```json
{
  "report_id": 1,
  "download_url": "/api/v1/reports/1/file",
  "filename": "career_report_20260909.docx"
}
```

---

## 聊天接口

### 创建会话
```
POST /api/v1/chat/sessions
```

**请求体**:
```json
{
  "title": "职业规划咨询"
}
```

### 获取会话列表
```
GET /api/v1/chat/sessions
```

### 获取会话详情
```
GET /api/v1/chat/sessions/{session_id}
```

### 发送消息 (SSE)
```
POST /api/v1/chat/sessions/{session_id}/messages
```

**请求体**:
```json
{
  "content": "我想了解软件工程师的发展前景"
}
```

**响应**: Server-Sent Events 流
```
data: {"role": "assistant", "content": "软件工程师...", "done": false}
data: {"role": "assistant", "content": "", "done": true}
```

---

## 管理后台接口

> 所有管理接口需要 `admin` 角色权限

### 仪表盘
```
GET /api/v1/admin/dashboard/overview     // 概览统计
GET /api/v1/admin/dashboard/user-growth  // 用户增长
GET /api/v1/admin/dashboard/job-categories // 岗位分布
GET /api/v1/admin/dashboard/match-stats   // 匹配统计
GET /api/v1/admin/dashboard/system-health // 系统健康
```

### 用户管理
```
GET    /api/v1/admin/users              // 用户列表
GET    /api/v1/admin/users/{user_id}    // 用户详情
GET    /api/v1/admin/users/{user_id}/stats // 用户统计
PUT    /api/v1/admin/users/{user_id}    // 更新用户
POST   /api/v1/admin/users/{user_id}/reset-password // 重置密码
DELETE /api/v1/admin/users/{user_id}    // 删除用户
```

### 岗位管理
```
GET    /api/v1/admin/jobs               // 岗位列表
POST   /api/v1/admin/jobs               // 创建岗位
GET    /api/v1/admin/jobs/{job_id}      // 岗位详情
PUT    /api/v1/admin/jobs/{job_id}      // 更新岗位
DELETE /api/v1/admin/jobs/{job_id}      // 删除岗位
```

### 数据导入
```
POST   /api/v1/admin/import/upload      // 上传文件
GET    /api/v1/admin/import/jobs        // 导入任务列表
GET    /api/v1/admin/import/jobs/{job_id} // 导入进度 (SSE)
DELETE /api/v1/admin/import/jobs/{job_id} // 删除任务
```

### 匹配管理
```
GET    /api/v1/admin/matching/results   // 匹配结果列表
GET    /api/v1/admin/matching/feedbacks // 反馈列表
GET    /api/v1/admin/matching/weights   // 维度权重列表
POST   /api/v1/admin/matching/weights   // 创建维度权重
PUT    /api/v1/admin/matching/weights/{id} // 更新维度权重
DELETE /api/v1/admin/matching/weights/{id} // 删除维度权重
```

### 系统配置
```
GET    /api/v1/admin/system/configs     // AI 配置列表
POST   /api/v1/admin/system/configs     // 创建配置
PUT    /api/v1/admin/system/configs/{id} // 更新配置
DELETE /api/v1/admin/system/configs/{id} // 删除配置
```

---

## 错误响应

所有接口在发生错误时返回统一格式：

```json
{
  "detail": "错误描述信息"
}
```

**HTTP 状态码**:

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |
| 400 | 请求参数错误 |
| 401 | 未认证 |
| 403 | 权限不足 |
| 404 | 资源不存在 |
| 409 | 资源冲突 |
| 422 | 验证错误 |
| 500 | 服务器内部错误 |

---

## 认证说明

1. 调用登录接口获取 `access_token`
2. 在后续请求头中添加: `Authorization: Bearer <token>`
3. Token 有效期: 24 小时 (可在配置中调整)

---

**版本**: v1.0.0 | **更新日期**: 2026-09-09
