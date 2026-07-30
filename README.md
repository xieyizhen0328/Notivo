# Notivo — 智能会议纪要

脱离硬件的录音转会议纪要工具。导入本地录音 → AI 多模板纪要生成 → 一键思维导图。

## 快速开始

### 1. 配置 API Key

```bash
cp .env.example .env
# 编辑 .env，填入 NOTIVO_API_KEY
```

### 2. 启动后端

```bash
python server.py
# → http://localhost:8000
```

### 3. 打开前端

浏览器访问 http://localhost:8000

或直接打开 `index.html`，在「我」→「API设置」中配置后端地址为 `http://localhost:8000`。

## 架构

```
浏览器 (index.html)  ←→  FastAPI (server.py)  ←→  AI APIs
                              │
                         SQLite (data/notivo.db)
```

## API 端点

| 端点 | 说明 |
|------|------|
| POST /api/transcribe | 上传音频 → Whisper 转录 |
| POST /api/generate | 生成纪要（SSE 流式） |
| POST /api/chat | AI 追问（SSE 流式） |
| GET /api/health | 健康检查 |
| CRUD /api/files | 文件管理 |
| CRUD /api/minutes | 纪要管理 |
| CRUD /api/projects | 项目管理 |
| CRUD /api/todos | 待办管理 |
| GET/PUT /api/glossary | 语音词库 |
| GET/PUT /api/config | 服务器配置 |

完整文档：启动后访问 http://localhost:8000/docs

## 功能

- 🎙️ 本地录音导入 + 上传到服务器
- ✨ 15 套纪要模板
- 💬 AI 流式对话（Anthropic / OpenAI 兼容）
- 🧠 一键思维导图
- 📋 纪要历史 + 搜索
- ✅ 待办看板
- 📝 语音词库 + 行业偏好
- 📁 项目分组管理

## 技术栈

- 前端：单 HTML 文件（vanilla JS）
- 后端：FastAPI + SQLite + httpx
- AI：Anthropic Claude / OpenAI GPT-4o + Whisper
