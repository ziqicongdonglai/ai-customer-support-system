# Runtime 配置

本文档说明 AI Customer Support System 的 reviewer demo topology、配置契约，以及 database / demo / RAG bootstrap 与 readiness contract。

## 1. 选定的 topology 与运行前提

当前选定目标是 private、single-host、single-instance 的 reviewer demo：

```text
PostgreSQL + FastAPI backend -> Docker Compose
Next.js frontend            -> host npm process
```

Runtime 版本：

- Python 3.10
- Node.js 24
- 支持 Compose 的 Docker

默认可重复运行的 AI 模式是 `mock`。Live DeepSeek 是可选模式，需要用户自行提供 API key。该 topology 不面向 anonymous public paid-LLM service。

## 2. Backend 环境配置

在 `backend` 中创建本地环境文件：

```powershell
Copy-Item .env.example .env
```

仓库中的示例配置是安全的，并与 Docker Compose topology 对齐。不要提交生成的 `.env` 或真实 API key。

### 必需配置

| 环境变量 | 配置契约 |
| --- | --- |
| `DATABASE_URL` | 必须提供，并且必须是可解析、driver 为 `postgresql+asyncpg` 的 URL。 |

Startup validation 只检查 `DATABASE_URL` 是否存在、URL 语法以及 driver。它不会连接 PostgreSQL，不会向 server 验证 credentials，也不会检查 migration state 或 schema readiness。

### Provider 配置

| 环境变量 | 默认值 | 配置契约 |
| --- | --- | --- |
| `LLM_PROVIDER` | `mock` | 只允许 `mock`、`deepseek`。 |
| `DEEPSEEK_API_KEY` | 空 | 仅当 `LLM_PROVIDER=deepseek` 时必需；属于 secret。 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | DeepSeek endpoint。 |
| `DEEPSEEK_MODEL` | `deepseek-v4-flash` | DeepSeek model name。 |
| `REQUEST_TIMEOUT` | `60` | 以秒为单位的正数。 |

`LLM_PROVIDER=mock` 不发起 live LLM 调用，也不需要 DeepSeek key。`LLM_PROVIDER=deepseek` 会在 startup 时要求 `DEEPSEEK_API_KEY` 非空；key 是否有效、provider availability、quota、network behavior 与 HTTP failures 仍属于 request-time concerns。

### Application 与 RAG 配置

| 环境变量 | 默认值 | 配置契约 |
| --- | --- | --- |
| `MAX_CONTEXT_TOKENS` | `4000` | 正整数。 |
| `DEFAULT_SYSTEM_PROMPT` | 内置 assistant prompt | Chat system prompt。 |
| `EMBEDDING_MODEL` | `BAAI/bge-small-zh-v1.5` | 非空 model identifier。 |
| `RAG_VECTOR_STORE_PATH` | `/app/vector_data` | 由 Compose volume 支持的 Docker 路径。 |
| `RAG_COLLECTION_NAME` | `business_knowledge` | Application 与 business demo 共用的 canonical collection。 |
| `RAG_TOP_K` | `3` | 正整数。 |

`RAG_VECTOR_STORE_PATH=/app/vector_data` 是 Docker-oriented 路径。直接在 host 运行 backend 时，应显式覆盖该值；例如 working directory 为 backend root 时可使用 `./vector_data`。

Startup validation 不会初始化 Chroma，不会测试路径是否 writable，也不会加载或下载 Embedding Model。

### CORS

`CORS_ORIGINS` 默认值为 `http://localhost:3000`。它是以逗号分隔的精确 HTTP/HTTPS origins 列表，配置项两侧 whitespace 会被移除。

空值、空配置项、trailing comma、wildcard `*`、credentials，以及包含 path、query 或 fragment 的值都会被拒绝。该契约用于保持 private reviewer exposure model；CORS 不是 authentication，也不是 abuse protection。

## 3. Database / demo / RAG bootstrap

Migration、seed 与 RAG ingestion 是分离的 explicit one-time operator steps。选定的 Docker topology 使用以下顺序：

```powershell
cd backend
docker compose build api
docker compose up -d --wait postgres
docker compose run --rm api alembic upgrade head
docker compose run --rm api python -m app.scripts.seed_business_fixtures postgresql+asyncpg://ai_user:ai_password@postgres:5432/ai_chat --verify
docker compose run --rm api python -m app.scripts.ingest_business_knowledge
docker compose up -d api
```

Production 与 development Dockerfile 都会先从 PyTorch 官方 CPU index 安装 `torch==2.13.0`，再安装共享 `requirements.txt`，并在 build 内断言实际 artifact 为 `2.13.0+cpu`、`torch.version.cuda is None` 且 CUDA 不可用。共享 requirements 继续作为逻辑版本清单，不改变 host developer install。

CPU Torch artifact 仍需要访问 `https://download.pytorch.org/whl/cpu`。这与首次 RAG ingestion 可能访问 Hugging Face 下载 embedding model 是两个独立的 network/cache boundary；当前流程不声明 offline build。

PostgreSQL healthcheck 使用 image 内置的 `pg_isready`，只表示 PostgreSQL 正在接受连接。API 会等待 `postgres` 达到 `service_healthy`，但 healthcheck 不表示 migrations、fixtures、RAG 或 application readiness 已完成。

`alembic upgrade head` 独立负责 schema；`seed_business_fixtures --verify` 独立创建并重复验证 28 条 deterministic fixtures；business ingestion 在 fresh `business_knowledge` collection 中写入 4 documents / 11 chunks。非空 collection 会明确拒绝再次 ingestion，不会重复写入。

Business ingestion 可能在第一次运行时加载或下载 embedding model。未缓存模型且网络不可用会导致 RAG bootstrap 失败，但不会使 database readiness 失败。若 disposable ingestion 中断并留下 partial non-empty collection，删除该隔离的 disposable RAG state 后从 fresh state 重试；当前不提供 replacement 或 partial-recovery lifecycle。

### Health contracts

| Endpoint | Contract |
| --- | --- |
| `/health` | Process liveness；不访问外部 dependency。 |
| `/health/db` | Database connectivity；执行 `SELECT 1`，不验证 schema。 |
| `/health/ready` | Schema-aware readiness；要求 database current Alembic revision 等于 repository unique head。 |

`/health/ready` 在 database 不可访问、`alembic_version` 缺失、revision 落后或 repository 无法确定唯一 head 时返回 HTTP 503。它不执行 migration/seed，不访问 fixtures、Chroma、embedding model、DeepSeek 或 retrieval evaluation。

启动后可验证：

```powershell
Invoke-WebRequest http://localhost:8000/health
Invoke-WebRequest http://localhost:8000/health/db
Invoke-WebRequest http://localhost:8000/health/ready
```

```text
PostgreSQL healthy
≠ schema ready
≠ reviewer/demo bootstrap complete
```

## 4. Backend startup

选定的 Docker topology 使用：

```powershell
cd backend
docker compose up -d api
```

如需有意在 host 上运行 backend，应先激活 Python 3.10 环境，提供 host 可访问的 `DATABASE_URL`，覆盖 `RAG_VECTOR_STORE_PATH`，然后运行：

```powershell
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

配置验证成功只表示配置值已提供、可解析且字段关系一致；dependency 与 schema 状态分别由 PostgreSQL healthcheck、显式 bootstrap 和 `/health/ready` 验证。

## 5. Frontend 环境配置

在 `frontend` 中创建本地环境文件：

```powershell
Copy-Item .env.example .env.local
```

选定的 topology 使用：

```dotenv
NEXT_PUBLIC_API_URL=http://localhost:8000
```

`NEXT_PUBLIC_API_URL` 是 public build-time 配置。Next.js 会在 build 时将它写入浏览器 bundle；缺失或空白配置会在 Next config evaluation 阶段以 `NEXT_PUBLIC_API_URL is required` 明确失败，而不是让浏览器发出 `undefined/...` 请求。

**修改 `NEXT_PUBLIC_API_URL` 后必须重新 build frontend。** 仅重启已经 build 完成的 `npm run start` 进程不会替换 bundle 中已嵌入的值。

该值必须是 origin 且不能带 trailing slash；selected topology 使用 `http://localhost:8000`。当前 `next start` 也会 evaluate `next.config.ts`，因此 start 时仍需提供同一非空值，但 start-time value 不会改写已 build 的 browser bundle。

## 6. Frontend 命令

开发模式：

```powershell
cd frontend
npm ci
npm run dev
```

Production-style host 命令：

```powershell
npm ci
npm run lint
npm run build
npm run start
```

Frontend 使用 repository system CSS font stack；production build 不再通过 `next/font/google` 获取 Google Fonts。

启动后先验证 frontend `/` 与其引用的 `/_next/static/...` assets 返回 200，再执行 bounded browser smoke：使用 Mock Provider、RAG OFF 发送一条 streaming message，确认 Conversation 出现在 sidebar，并在 refresh/reselect 后确认 user 与 completed assistant messages 从 PostgreSQL reload。HTTP 200 不能替代 browser/CORS/hydration evidence。

RAG 不属于 minimum browser smoke。完成 business knowledge ingestion 且 embedding model 可用后，另行发送一次 `use_rag=true` API request，要求 non-empty `sources` event 与 completed stream。

## 7. Validation 边界

```text
Configuration validation
-> 环境变量名称、存在性、语法、允许值、数值范围

Database readiness
-> PostgreSQL connectivity 与 Alembic current/head comparison

Migration / demo / RAG bootstrap
-> 明确、分离、有序的 one-time setup 与 verification
```

任何 startup configuration check 都不会连接 PostgreSQL、访问 DeepSeek、初始化 Chroma、下载 Embedding Model 或执行 migrations。
