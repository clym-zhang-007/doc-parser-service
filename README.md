# doc-parser-service

文档解析 API 服务（V1）：异步任务 + PostgreSQL + Redis/Celery。

## 快速说明

- 开发基线：`docs/V1-开发基线.md`
- 架构决策：`docs/DECISIONS.md`

## 当前进度（截至 2026-04-04）

### 已完成

- [x] 目录与 Docker 骨架（api / worker / redis / postgres）
- [x] FastAPI 应用入口与路由拆分（`app/main.py`，`app/api/health.py`、`app/api/jobs.py`）
- [x] 核心 HTTP 接口：`GET /health`，`POST /v1/jobs`（**multipart 上传文件**），`GET /v1/jobs/{job_id}`，`GET /v1/jobs/{job_id}/result`
- [x] SQLAlchemy 模型 `Job`（`app/core/models.py`）与会话（`app/core/database.py`）
- [x] Alembic 迁移（`alembic/`，首版 `0001_initial_jobs`）；`docker compose` 通过一次性 **`migrate` 服务** 执行 `alembic upgrade head`，`api` / `worker` 在其成功结束后再启动
- [x] Celery Worker 与任务 `jobs.parse_document`（当前为占位解析结果，状态机 `queued → running → success/failed`）
- [x] Pydantic 契约（`app/schemas/__init__.py`）

### 尚未完成（相对 V1 基线）

- [ ] LlamaIndex（或等价）真实解析与 V1 约定统一结果 JSON（document/blocks/meta）
- [ ] 与基线一致的错误码与 HTTP 映射
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

创建任务示例（需安装依赖后本地或容器内执行，`file` 为实际路径）：

```bash
curl -s -X POST http://localhost:8000/v1/jobs -F "file=@./sample.pdf"
```

允许扩展名：`.pdf`、`.docx`、`.txt`、`.md`、`.markdown`。文件写入 `storage/uploads/{job_id}/`，库字段 `jobs.storage_path` 存相对路径。

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
| `alembic/` | 数据库迁移 |

## 下一步（建议优先级）

1. **真实解析**：按 `file_type` 读 `storage_path` 对应文件，接入 LlamaIndex，输出基线约定的 JSON，写入 `result_json`。
2. **错误与契约**：统一错误码、422/404/409 等映射；OpenAPI 示例与版本说明。
3. **测试与运维**：`pytest` 覆盖 API 与任务 happy path；可选结构化日志与 `/health` 扩展（db/redis 探测）。
