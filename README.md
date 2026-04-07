# doc-parser-service

文档解析 API 服务（V1）：异步任务 + PostgreSQL + Redis/Celery。

## 快速说明

- 开发基线：`docs/V1-开发基线.md`
- 架构决策：`docs/DECISIONS.md`

## 版本信息（与代码一致，便于追溯）

| 项目 | 当前值 | 代码位置 |
|------|--------|----------|
| HTTP API / OpenAPI 版本 | `0.1.0` | `app/main.py` → `FastAPI(..., version="0.1.0")` |
| 上传页（前端包版本） | `0.1.0` | `frontend/package.json` → `version` |
| 解析结果 `meta.blocks_schema_version` | `1.6` | `app/services/document_parse.py` → `BLOCKS_SCHEMA_VERSION` |

**文档同步日期**：`2026-04-07`（与 `docs/V1-开发基线.md` 中「实现进度对照」表头一致）。若升级 API 版本或分块 schema，请同时改上表与基线文档。

## 当前进度（截至 2026-04-07）

### 已完成

- [x] 目录与 Docker 骨架（api / worker / redis / postgres）
- [x] FastAPI 应用入口与路由拆分（`app/main.py`，`app/api/health.py`、`app/api/jobs.py`）
- [x] 核心 HTTP 接口：`GET /health`，`POST /v1/jobs`（**multipart 上传文件**），`GET /v1/jobs/{job_id}`，`GET /v1/jobs/{job_id}/result`
- [x] SQLAlchemy 模型 `Job`（`app/core/models.py`）与会话（`app/core/database.py`）
- [x] Alembic 迁移（`alembic/`，首版 `0001_initial_jobs`）；`docker compose` 通过一次性 **`migrate` 服务** 执行 `alembic upgrade head`，`api` / `worker` 在其成功结束后再启动
- [x] Celery Worker 与任务 `jobs.parse_document`（**LlamaIndex `SimpleDirectoryReader` + 按类型回退**，输出 `document` / `blocks` / `meta` / `error`）
- [x] 统一错误体与基础日志（`app/core/error_handlers.py` + `app/core/errors.py`；失败时统一输出 `{"error": {"code", "message"}}`，并在全局/worker 侧记录异常上下文）
- [x] Pydantic 契约（`app/schemas/__init__.py`）

### 尚未完成（相对 V1 基线）

- [ ] 结果 JSON 字段与基线进一步对齐（如按页块、更细 `meta`）；可选纯 LlamaIndex、去掉回退
- [ ] 与基线一致的错误码覆盖与 OpenAPI 示例（已有基础版：错误体统一、上传/解析失败等场景抛出 `UNSUPPORTED_FILE_TYPE` / `FILE_TOO_LARGE` / `JOB_NOT_FOUND` / `RESULT_NOT_READY` / `PARSE_FAILED` / `INTERNAL_ERROR`，以及 HTTP 422 的 `VALIDATION_ERROR`）
- [ ] 自动化测试与样例文档回归

## 使用 Docker 运行

### 1) 启动服务

在项目根目录执行：

```bash
docker compose up --build
```

启动后会包含 5 个服务（其中 `migrate` 跑完迁移后退出）：

- `doc-parser-migrate`（一次性：`alembic upgrade head`）
- `doc-parser-api`（FastAPI，映射 `8000`）
- `doc-parser-worker`（Celery Worker）
- `doc-parser-redis`（broker/result backend）
- `doc-parser-postgres`（数据库）

健康检查请使用 **HTTP** 与 **8000** 端口，例如：`http://localhost:8000/health`（不要用未配置的 `https` 或其它端口）。

**上传页（React + Vite + Tailwind）**：`docker compose up --build` 后打开 `http://localhost:8000/` 或 `http://localhost:8000/ui/`（静态资源来自 `frontend/dist`）。本地联调前端见下文「前端开发」。

创建任务示例（需安装依赖后本地或容器内执行，`file` 为实际路径）：

```bash
curl -s -X POST http://localhost:8000/v1/jobs -F "file=@./sample.pdf"
```

允许扩展名：`.pdf`、`.docx`、`.txt`、`.md`、`.markdown`。文件写入 `storage/uploads/{job_id}/`，库字段 `jobs.storage_path` 存相对路径。

### 前端开发（可选）

技术栈：**Vite 6 + React 18 + TypeScript + Tailwind CSS**（`frontend/`）。

```bash
cd frontend
npm install
npm run dev
```

浏览器访问 **`http://localhost:5173/ui/`**（`vite.config.ts` 已设 `base: '/ui/'`，并将 `/v1`、`/health`、`/docs` 等代理到本机 `8000`）。请先在本机启动 API：`uvicorn app.main:app --reload` 或使用 Docker 只跑后端相关容器。

生产构建：

```bash
cd frontend && npm run build
```

生成 `frontend/dist/` 后，FastAPI 会在 `/ui/` 托管；未构建时访问 `/` 会跳转到 `/docs`。

**Docker Compose 使用卷 `./:/app` 时**：镜像里构建的 `frontend/dist` 会被本机目录覆盖。若本机没有 `frontend/dist`，上传页不可用，请在仓库根目录执行一次 `cd frontend && npm run build`，或临时去掉 compose 里的 `volumes` 仅用镜像内文件调试。

### 2) 数据库迁移（本地/CI 手动时）

`docker compose up` 时会先由 **`migrate` 容器** 执行 `alembic upgrade head`。若在宿主机单独操作，需设置 `DATABASE_URL` 并安装依赖后执行：

```bash
alembic upgrade head
```

模型变更后应使用 `alembic revision --autogenerate -m "说明"` 生成迁移并审阅后再提交。

### 3) 停止服务

```bash
docker compose down
```

如需同时清理数据库卷：

```bash
docker compose down -v
```

### Docker 构建：拉取 `node` 镜像失败（如 USTC 镜像 `EOF`）

构建前端阶段需要拉取 Node 基础镜像。若日志中出现 `docker.mirrors.ustc.edu.cn`…`EOF` 或 `failed to resolve source metadata`，属于**镜像加速器/网络**问题，不是业务代码错误。可依次尝试：

1. **重试**：`docker compose build --no-cache`（偶发断线）。
2. **换源或直连**：在 Docker Desktop → Settings → Docker Engine 里调整 `registry-mirrors`（换一个可用镜像或暂时移除镜像列表，改走官方 `registry-1.docker.io`），应用后重启 Docker。
3. **先手动拉取**：`docker pull node:20-alpine`，成功后再 `docker compose up --build`。

当前 Dockerfile 使用 **`node:20-alpine`**（LTS）。

## 主要代码路径

| 路径 | 说明 |
|------|------|
| `app/main.py` | FastAPI 实例与路由注册 |
| `app/api/health.py` | 健康检查 |
| `app/api/jobs.py` | 作业相关 API |
| `app/core/models.py` | ORM 模型 |
| `app/core/database.py` | Engine、Session、`get_db` |
| `app/workers/celery_app.py` | Celery 应用与任务 |
| `app/schemas/__init__.py` | 请求/响应模型 |
| `app/services/storage.py` | 上传落盘与路径解析 |
| `app/services/document_parse.py` | LlamaIndex 解析与 V1 结果组装 |
| `alembic/` | 数据库迁移 |
| `frontend/` | React 前端源码；`frontend/dist` 为构建输出 |

## 解析结果 `meta`（分块追溯）

成功解析时，`result_json` 内 `meta` 除 `file_type`、`parser`、`char_count` 等外，还包含：

- **`blocks_schema_version`**：当前为 `1.6`（与 `app/services/document_parse.py` 中常量一致）；分块字段含义或规则变更时递增，便于前后端与离线分析对齐。
- **`blocks[].char_count`**：`1.4` 起每个分块含主体字符数（与块内 `text` 长度一致，含换行）；英文约 `tokens ≈ char_count / 4`，中文视分词器而定，仅作粗算。
- **`structure_quality`**（仅 DOCX 结构化策略）：结构识别质量摘要，含 `style_hit_ratio` / `numbering_hit_ratio` / `heuristic_hit_ratio` / `table_hit_ratio` / `avg_confidence` 等指标。
- **`block_strategy`**：本次 `blocks` 的**分块策略名**（与「全文用何 loader 抽取」的 `parser` 不同）。取值示例：
  - `markdown.heading_list_v4`：在 v3 基础上，GFM **管道表**为 `table`（`text` 为源码、`rows` 为单元格矩阵）；**整行仅** `![alt](url)` / `[label](url)` 时为 `image` / `link`（含 `url` 等字段，`text` 为对应 Markdown 片段）；行内混排链接与图片仍留在 `paragraph`。
  - `txt.paragraph_v1`：TXT 软换行修复 + 段落，再经合并/切分。
  - `docx.structure_v1_1`：DOCX 由 `python-docx` 按结构抽取（`heading`/`paragraph`/`list_item`→`list`/`table`），并附 `source`+`confidence`；样式缺失时启发式兜底。
  - `simple.blankline_v1`：PDF 等暂未定制时按空行分段兜底。

详见 `docs/V1-开发基线.md` 中「结果 JSON 与分块策略」。

## 下一步（建议优先级）

1. **结果与体验**：细化 `blocks`（按页/标题/段落更稳定）与 `meta`；逐步收敛 blocks 的切分策略与回退逻辑。
2. **错误与契约（后置精修）**：补齐缺口的错误码覆盖、以及最小必需的 OpenAPI 示例；失败路径的字段一致性优先。
3. **测试与运维（后置）**：`pytest` 覆盖 happy path 与失败路径；可选结构化日志与 `/health` 扩展（db/redis 探测）。
