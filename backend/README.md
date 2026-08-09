# 后端 — FastAPI

企业级 LLM 智能客服系统后端：RAG 问答（检索增强生成）、SSE 流式输出、知识库管理、多轮对话、每日限额。

## 技术栈

- **框架**: FastAPI + SQLAlchemy 2.x + PyMySQL
- **LLM**: DeepSeek API（OpenAI 兼容协议，`deepseek-chat`，流式）
- **Embedding**: 本地 `bge-small-zh-v1.5`（sentence-transformers），可切换 OpenAI 兼容端点
- **向量库**: Chroma 本地持久化模式（免独立服务）
- **数据库**: MySQL 8（Docker，见 docker-compose.yml）

## 环境要求

- Python 3.10+
- Docker（运行 MySQL）

## 启动步骤

```bash
# 1. 启动 MySQL（首次会自动拉取镜像）
docker compose up -d

# 2. 创建虚拟环境并安装依赖（中国大陆可用清华镜像加速）
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 3. 配置环境变量
cp .env.example .env
#    编辑 .env，填入你的 DeepSeek API Key：
#    LLM_API_KEY=sk-xxxxxxxx

# 4. 初始化数据库（建表 + 管理员账号；密码必须经环境变量注入）
#    Windows: $env:ADMIN_PASSWORD = "你的强密码"   Linux: export ADMIN_PASSWORD="你的强密码"
.venv/Scripts/python scripts/init_db.py
#    管理员账号：13800000000 / 上述密码（is_admin=true）

# 5. 启动服务（首次启动会自动下载 embedding 模型并向量化示例文档）
.venv/Scripts/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

启动后访问：
- API 文档（Swagger）: http://localhost:8000/docs
- 服务状态: http://localhost:8000/

## API Key 配置方式

所有密钥通过 `.env` 文件注入（参考 `.env.example`），**不要提交 `.env` 到仓库**。

| 变量 | 说明 |
|------|------|
| `LLM_API_KEY` | DeepSeek API Key（必填，用于对话/意图/追问） |
| `LLM_BASE_URL` | 默认 https://api.deepseek.com，可换任意 OpenAI 兼容端点 |
| `EMBEDDING_PROVIDER` | `local_bge`（默认）或 `openai_compatible` |
| `HF_ENDPOINT` | 模型下载镜像，中国大陆默认 hf-mirror.com |

## 目录结构

```
app/
├── main.py            # 入口 + 启动时种子文档向量化
├── config.py          # 环境配置
├── database.py        # SQLAlchemy 引擎
├── models/            # 9 张表 ORM
├── schemas/           # Pydantic 模型
├── routers/           # auth / chat / knowledge / sessions / admin / memory
└── services/          # rag / llm / embedding / vector_store / knowledge / usage / auth / memory
scripts/
├── init_db.py         # 建表 + 种子数据
data/seed_docs/        # 示例知识库文档（启动自动向量化）
```

## 测试

```bash
# 单元/集成测试
.venv/Scripts/python -m pytest tests/ -v
# 端到端冒烟测试
.venv/Scripts/python scripts/smoke_test.py
```
