"""
Notivo Backend — FastAPI server
Run: python server.py
"""
import os, json, uuid, time, asyncio, sqlite3
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import AsyncOpenAI

# ── Config ──────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "notivo.db"
ENV_PATH = BASE_DIR / ".env"

DATA_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)

# Load .env
if ENV_PATH.exists():
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# ── DB ──────────────────────────────────────────────────
def get_db() -> sqlite3.Connection:
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db

def init_db():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS files (
            id TEXT PRIMARY KEY, name TEXT, size INT, duration REAL,
            path TEXT, transcript TEXT DEFAULT '', project_id TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS minutes (
            id TEXT PRIMARY KEY, title TEXT, markdown TEXT, template_id TEXT,
            file_id TEXT, project_id TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY, name TEXT, color TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS todos (
            id TEXT PRIMARY KEY, text TEXT, done INT DEFAULT 0,
            minute_id TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS glossary (
            key TEXT PRIMARY KEY, value TEXT
        );
    """)
    db.commit()
    db.close()

init_db()

# ── Helpers ─────────────────────────────────────────────
def now(): return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def get_config(key: str, default=None):
    db = get_db()
    row = db.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
    db.close()
    return row["value"] if row else default

def set_config(key: str, value: str):
    db = get_db()
    db.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
    db.commit()
    db.close()

def get_provider_config():
    # DB values take priority, env vars as fallback
    return {
        "provider": get_config("provider") or os.environ.get("NOTIVO_PROVIDER", "anthropic"),
        "model": get_config("model") or os.environ.get("NOTIVO_MODEL", "claude-sonnet-5"),
        "api_key": get_config("api_key") or os.environ.get("NOTIVO_API_KEY", ""),
        "base_url": get_config("base_url") or os.environ.get("NOTIVO_BASE_URL", ""),
        "whisper_key": get_config("whisper_key") or os.environ.get("NOTIVO_WHISPER_KEY", ""),
    }

# ── AI Clients ──────────────────────────────────────────
def get_llm_response_stream(cfg: dict, system_prompt: str, messages: list) -> httpx.AsyncClient:
    """Returns an httpx async client request for streaming"""
    if cfg["provider"] == "anthropic":
        return _anthropic_stream(cfg, system_prompt, messages)
    else:
        return _openai_stream(cfg, system_prompt, messages)

async def _anthropic_stream(cfg, system, messages):
    """Stream from Anthropic Messages API"""
    body = {
        "model": cfg["model"],
        "system": system,
        "messages": messages,
        "max_tokens": 4096,
        "stream": True,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST", "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": cfg["api_key"],
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body,
        ) as resp:
            if resp.status_code != 200:
                text = await resp.aread()
                raise HTTPException(resp.status_code, f"Anthropic error: {text.decode()[:200]}")
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                        if data.get("type") == "content_block_delta":
                            delta = data.get("delta", {})
                            if delta.get("text"):
                                yield f"data: {json.dumps({'text': delta['text']})}\n\n"
                    except json.JSONDecodeError:
                        pass

async def _openai_stream(cfg, system, messages):
    """Stream from OpenAI-compatible Chat Completions API"""
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)
    base_url = cfg.get("base_url", "https://api.openai.com").rstrip("/")
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST", f"{base_url}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {cfg['api_key']}",
                "content-type": "application/json",
            },
            json={"model": cfg["model"], "messages": msgs, "stream": True},
        ) as resp:
            if resp.status_code != 200:
                text = await resp.aread()
                raise HTTPException(resp.status_code, f"OpenAI error: {text.decode()[:200]}")
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    if line.strip() == "data: [DONE]":
                        continue
                    try:
                        data = json.loads(line[6:])
                        content = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if content:
                            yield f"data: {json.dumps({'text': content})}\n\n"
                    except json.JSONDecodeError:
                        pass

# ── App ─────────────────────────────────────────────────
app = FastAPI(title="Notivo API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Models ──────────────────────────────────────────────
class GenerateRequest(BaseModel):
    template_id: str
    file_id: str
    user_instruction: str = ""

class ChatRequest(BaseModel):
    messages: list
    system_prompt: str = ""

class ProjectCreate(BaseModel):
    name: str
    color: str = "#4F46E5"

class TodoCreate(BaseModel):
    text: str
    minute_id: str = ""

class TodoUpdate(BaseModel):
    done: bool

class GlossaryUpdate(BaseModel):
    words: list = []
    industry: str = ""

class ConfigUpdate(BaseModel):
    provider: str = "anthropic"
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    whisper_key: str = ""

# ── AI Proxy Endpoints ──────────────────────────────────

@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...)):
    """Transcribe audio via OpenAI Whisper API"""
    cfg = get_provider_config()
    key = cfg["whisper_key"] or cfg["api_key"]
    if not key:
        raise HTTPException(400, "请先配置 API Key")

    # Save uploaded file
    ext = Path(file.filename).suffix or ".m4a"
    file_id = "f_" + uuid.uuid4().hex[:12]
    save_path = UPLOAD_DIR / f"{file_id}{ext}"
    content = await file.read()
    save_path.write_bytes(content)

    # Call Whisper via OpenAI SDK
    client = AsyncOpenAI(api_key=key)
    try:
        with open(save_path, "rb") as f:
            result = await client.audio.transcriptions.create(
                model="whisper-1", file=f, language="zh",
            )
        transcript = result.text
    except Exception as e:
        raise HTTPException(500, f"Whisper 转录失败: {str(e)}")

    # Save file record
    db = get_db()
    db.execute(
        "INSERT INTO files (id, name, size, duration, path, transcript, project_id, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (file_id, file.filename, len(content), 0, str(save_path), transcript, "", now()),
    )
    db.commit()
    db.close()

    return {"file_id": file_id, "text": transcript}


@app.post("/api/generate")
async def generate(req: GenerateRequest, request: Request):
    """Generate meeting minutes — transcribe + LLM, streaming SSE"""
    cfg = get_provider_config()
    if not cfg["api_key"]:
        raise HTTPException(400, "请先配置 API Key")

    # Get file transcript
    db = get_db()
    file_row = db.execute("SELECT * FROM files WHERE id=?", (req.file_id,)).fetchone()
    db.close()

    if not file_row:
        raise HTTPException(404, "文件不存在")

    transcript = file_row["transcript"]
    if not transcript:
        raise HTTPException(400, "文件尚未转录，请先调用 /api/transcribe")

    # Build prompt from template (simplified — frontend sends template_id, we match)
    templates = _get_templates()
    tpl = templates.get(req.template_id, templates.get("meeting", {}))
    system_prompt = tpl.get("system", "你是会议纪要助手。")
    prompt_template = tpl.get("prompt", "请生成会议纪要。")
    extra = f"\n\n用户附加指令：{req.user_instruction}" if req.user_instruction else ""
    full_prompt = f"{prompt_template}{extra}\n\n---\n以下为会议录音转录内容：\n\n{transcript}"

    async def event_stream():
        full_text = ""
        try:
            async for chunk in get_llm_response_stream(cfg, system_prompt, [{"role": "user", "content": full_prompt}]):
                data = json.loads(chunk.replace("data: ", ""))
                full_text += data.get("text", "")
                yield chunk
            # Save minute
            title = tpl.get("name", "会议纪要")
            minute_id = "m_" + uuid.uuid4().hex[:12]
            db2 = get_db()
            db2.execute(
                "INSERT INTO minutes (id, title, markdown, template_id, file_id, project_id, created_at) VALUES (?,?,?,?,?,?,?)",
                (minute_id, title, full_text, req.template_id, req.file_id, file_row["project_id"] or "", now()),
            )
            db2.commit()
            db2.close()
            # Extract todos
            _extract_todos_from_markdown(full_text, minute_id)
            yield f"data: {json.dumps({'done': True, 'minute_id': minute_id, 'title': title})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """Follow-up chat — streaming SSE"""
    cfg = get_provider_config()
    if not cfg["api_key"]:
        raise HTTPException(400, "请先配置 API Key")

    async def event_stream():
        full_text = ""
        try:
            async for chunk in get_llm_response_stream(cfg, req.system_prompt, req.messages):
                data = json.loads(chunk.replace("data: ", ""))
                full_text += data.get("text", "")
                yield chunk
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/health")
async def health():
    cfg = get_provider_config()
    has_key = bool(cfg["api_key"])
    return {"ok": True, "has_api_key": has_key, "provider": cfg["provider"]}

# ── Data CRUD Endpoints ─────────────────────────────────

# Files
@app.get("/api/files")
def list_files(project_id: str = ""):
    db = get_db()
    if project_id:
        rows = db.execute("SELECT * FROM files WHERE project_id=? ORDER BY created_at DESC", (project_id,)).fetchall()
    else:
        rows = db.execute("SELECT * FROM files ORDER BY created_at DESC").fetchall()
    db.close()
    return [dict(r) for r in rows]

@app.get("/api/files/{file_id}")
def get_file(file_id: str):
    db = get_db()
    row = db.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
    db.close()
    if not row:
        raise HTTPException(404, "文件不存在")
    return dict(row)

@app.post("/api/files")
async def upload_file(file: UploadFile = File(...), project_id: str = Form("")):
    ext = Path(file.filename).suffix or ".m4a"
    file_id = "f_" + uuid.uuid4().hex[:12]
    save_path = UPLOAD_DIR / f"{file_id}{ext}"
    content = await file.read()
    save_path.write_bytes(content)

    db = get_db()
    db.execute(
        "INSERT INTO files (id, name, size, duration, path, transcript, project_id, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (file_id, file.filename, len(content), 0, str(save_path), "", project_id, now()),
    )
    db.commit()
    db.close()
    return {"file_id": file_id, "name": file.filename, "size": len(content)}

@app.delete("/api/files/{file_id}")
def delete_file(file_id: str):
    db = get_db()
    row = db.execute("SELECT path FROM files WHERE id=?", (file_id,)).fetchone()
    if row and row["path"] and Path(row["path"]).exists():
        Path(row["path"]).unlink(missing_ok=True)
    db.execute("DELETE FROM files WHERE id=?", (file_id,))
    db.execute("DELETE FROM minutes WHERE file_id=?", (file_id,))
    db.execute("DELETE FROM todos WHERE minute_id IN (SELECT id FROM minutes WHERE file_id=?)", (file_id,))
    db.commit()
    db.close()
    return {"ok": True}

# Minutes
@app.get("/api/minutes")
def list_minutes(project_id: str = "", search: str = ""):
    db = get_db()
    q = "SELECT * FROM minutes WHERE 1=1"
    params = []
    if project_id:
        q += " AND project_id=?"
        params.append(project_id)
    if search:
        q += " AND (title LIKE ? OR markdown LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    q += " ORDER BY created_at DESC LIMIT 100"
    rows = db.execute(q, params).fetchall()
    db.close()
    return [dict(r) for r in rows]

@app.get("/api/minutes/{minute_id}")
def get_minute(minute_id: str):
    db = get_db()
    row = db.execute("SELECT * FROM minutes WHERE id=?", (minute_id,)).fetchone()
    db.close()
    if not row:
        raise HTTPException(404, "纪要不存在")
    return dict(row)

@app.delete("/api/minutes/{minute_id}")
def delete_minute(minute_id: str):
    db = get_db()
    db.execute("DELETE FROM minutes WHERE id=?", (minute_id,))
    db.execute("DELETE FROM todos WHERE minute_id=?", (minute_id,))
    db.commit()
    db.close()
    return {"ok": True}

# Projects
@app.get("/api/projects")
def list_projects():
    db = get_db()
    rows = db.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    db.close()
    return [dict(r) for r in rows]

@app.post("/api/projects")
def create_project(req: ProjectCreate):
    pid = "p_" + uuid.uuid4().hex[:8]
    db = get_db()
    db.execute("INSERT INTO projects (id, name, color, created_at) VALUES (?,?,?,?)", (pid, req.name, req.color, now()))
    db.commit()
    db.close()
    return {"id": pid, "name": req.name, "color": req.color}

@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str):
    db = get_db()
    db.execute("DELETE FROM projects WHERE id=?", (project_id,))
    db.commit()
    db.close()
    return {"ok": True}

# Todos
@app.get("/api/todos")
def list_todos():
    db = get_db()
    rows = db.execute("SELECT * FROM todos ORDER BY done ASC, created_at DESC").fetchall()
    db.close()
    return [dict(r) for r in rows]

@app.post("/api/todos")
def create_todo(req: TodoCreate):
    tid = "t_" + uuid.uuid4().hex[:8]
    db = get_db()
    db.execute("INSERT INTO todos (id, text, done, minute_id, created_at) VALUES (?,?,0,?,?)", (tid, req.text, req.minute_id, now()))
    db.commit()
    db.close()
    return {"id": tid}

@app.patch("/api/todos/{todo_id}")
def update_todo(todo_id: str, req: TodoUpdate):
    db = get_db()
    db.execute("UPDATE todos SET done=? WHERE id=?", (1 if req.done else 0, todo_id))
    db.commit()
    db.close()
    return {"ok": True}

@app.delete("/api/todos/{todo_id}")
def delete_todo(todo_id: str):
    db = get_db()
    db.execute("DELETE FROM todos WHERE id=?", (todo_id,))
    db.commit()
    db.close()
    return {"ok": True}

# Glossary
@app.get("/api/glossary")
def get_glossary():
    db = get_db()
    words_row = db.execute("SELECT value FROM glossary WHERE key='words'").fetchone()
    ind_row = db.execute("SELECT value FROM glossary WHERE key='industry'").fetchone()
    db.close()
    return {
        "words": json.loads(words_row["value"]) if words_row else [],
        "industry": ind_row["value"] if ind_row else None,
    }

@app.put("/api/glossary")
def update_glossary(req: GlossaryUpdate):
    db = get_db()
    db.execute("INSERT OR REPLACE INTO glossary (key, value) VALUES ('words', ?)", (json.dumps(req.words, ensure_ascii=False),))
    if req.industry:
        db.execute("INSERT OR REPLACE INTO glossary (key, value) VALUES ('industry', ?)", (req.industry,))
    else:
        db.execute("DELETE FROM glossary WHERE key='industry'")
    db.commit()
    db.close()
    return {"ok": True}

# Config
@app.get("/api/config")
def get_config_api():
    return {
        "provider": get_config("provider", "anthropic"),
        "model": get_config("model", "claude-sonnet-5"),
        "base_url": get_config("base_url", ""),
        "has_api_key": bool(get_config("api_key", "")),
        "has_whisper_key": bool(get_config("whisper_key", "")),
    }

@app.put("/api/config")
def update_config_api(req: ConfigUpdate):
    if req.provider: set_config("provider", req.provider)
    if req.model: set_config("model", req.model)
    if req.api_key: set_config("api_key", req.api_key)
    if req.base_url: set_config("base_url", req.base_url)
    if req.whisper_key: set_config("whisper_key", req.whisper_key)
    return {"ok": True}

# ── Templates (mirror frontend) ─────────────────────────
def _get_templates():
    return {
        "meeting": {"name":"标准会议纪要","system":"你是一位专业的会议记录员。请根据会议内容生成一份标准会议纪要。使用Markdown格式。","prompt":"请生成标准会议纪要，包含：\n## 会议基本信息\n## 议题讨论\n## 决议事项\n## 行动计划\n| 事项 | 负责人 | 截止时间 |\n## 下次会议安排"},
        "interview": {"name":"访谈/调研记录","system":"你是一位资深用户研究员。","prompt":"请生成访谈记录：\n## 访谈背景\n## 关键问答\n## 核心发现\n## 用户痛点\n## 待跟进事项"},
        "lecture": {"name":"课堂/讲座笔记","system":"你是一位学习笔记整理师。","prompt":"请生成学习笔记：\n## 课程主题\n## 知识框架\n## 重点概念\n## 关键词索引\n## 个人思考题"},
        "retrospective": {"name":"项目复盘","system":"你是一位敏捷教练。","prompt":"请生成复盘报告：\n## 项目概况\n## 亮点\n## 不足\n## 根因分析\n## 改进措施\n## 经验沉淀"},
        "client": {"name":"客户沟通记录","system":"你是一位商务助理。","prompt":"请生成沟通记录：\n## 沟通概要\n## 客户需求\n## 我方回应\n## 关键共识\n## 后续计划\n## 风险提示"},
        "brainstorm": {"name":"头脑风暴","system":"你是一位创新引导师。","prompt":"请生成整理报告：\n## 讨论主题\n## 观点聚类\n## 核心方向\n## 下一步行动\n## 发散思考"},
        "memo": {"name":"日常语音备忘","system":"你是一位个人效率助手。","prompt":"请生成备忘整理：\n## 要点摘要\n## 待办提取\n## 时间节点\n## 关联事项"},
        "medical": {"name":"医生问诊记录","system":"你是一位医疗记录员。","prompt":"请生成问诊记录：\n## 就诊信息\n## 症状描述\n## 问询要点\n## 诊断意见\n## 处置方案\n## 医嘱随访"},
        "legal": {"name":"法律咨询记录","system":"你是一位法律事务记录员。","prompt":"请生成咨询记录：\n## 咨询概要\n## 案情陈述\n## 咨询问题\n## 律师意见\n## 证据材料\n## 后续建议"},
        "sales": {"name":"销售跟进记录","system":"你是一位销售助理。","prompt":"请生成跟进记录：\n## 客户信息\n## 沟通概要\n## 客户需求\n## 我方方案\n## 异议应对\n## 下一步计划"},
        "prd": {"name":"产品评审会","system":"你是一位技术产品记录员。","prompt":"请生成评审记录：\n## 评审对象\n## 方案概述\n## 评审意见\n## 技术关注点\n## 决议\n## 待办"},
        "pitch": {"name":"投资人路演","system":"你是一位投融资分析师。","prompt":"请生成路演记录：\n## 项目概要\n## 核心亮点\n## 投资人提问\n## 关注顾虑\n## 后续跟进\n## 整体评估"},
        "academic": {"name":"学术研讨会","system":"你是一位学术秘书。","prompt":"请生成研讨记录：\n## 研讨主题\n## 核心论点\n## 研究方法\n## 讨论要点\n## 启发延伸\n## 参考文献"},
        "press": {"name":"新闻发布会","system":"你是一位公关记录员。","prompt":"请生成发布记录：\n## 发布概要\n## 内容要点\n## 记者问答\n## 敏感点\n## 传播建议"},
        "summary": {"name":"工作总结","system":"你是一位管理顾问。","prompt":"请生成总结报告：\n## 周期概述\n## 主要成果\n## 问题挑战\n## 数据复盘\n## 亮点自评\n## 改进计划\n## 下阶段规划"},
    }

def _extract_todos_from_markdown(markdown: str, minute_id: str):
    """Extract - [ ] items and save as todos"""
    db = get_db()
    for line in markdown.split("\n"):
        stripped = line.strip()
        if stripped.startswith("- [ ] ") or stripped.startswith("* [ ] "):
            text = stripped[6:].strip()
            if text:
                tid = "t_" + uuid.uuid4().hex[:8]
                db.execute(
                    "INSERT INTO todos (id, text, done, minute_id, created_at) VALUES (?,?,0,?,?)",
                    (tid, text, minute_id, now()),
                )
    db.commit()
    db.close()

# ── Serve Frontend ──────────────────────────────────────
# Serve PWA / static files. API routes (/api/*) match first, this catches everything else.
@app.get("/{filename:path}")
async def serve_static(filename: str):
    path = BASE_DIR / filename
    # Only serve files that exist and are within BASE_DIR
    try:
        resolved = path.resolve()
        if not str(resolved).startswith(str(BASE_DIR.resolve())):
            raise FileNotFoundError
        if resolved.is_file():
            media = None
            if filename.endswith(".js"): media = "application/javascript"
            elif filename.endswith(".json"): media = "application/json"
            elif filename.endswith(".png"): media = "image/png"
            elif filename.endswith(".svg"): media = "image/svg+xml"
            return FileResponse(resolved, media_type=media)
    except (FileNotFoundError, OSError):
        pass
    # SPA fallback: everything else → index.html
    return FileResponse(BASE_DIR / "index.html")

@app.get("/")
async def root():
    return FileResponse(BASE_DIR / "index.html")

# ── Main ────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    print(f"\n  Notivo API → http://localhost:{port}")
    print(f"  Docs       → http://localhost:{port}/docs\n")
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=True)
