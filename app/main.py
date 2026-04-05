"""FastAPI 应用入口。

职责：
1) 创建 FastAPI 实例并注册路由。
2) 数据库表结构由 Alembic 迁移维护（见 docker-compose 启动命令）。
"""

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.jobs import router as jobs_router

app = FastAPI(title="doc-parser-service", version="0.1.0")

app.include_router(health_router)
app.include_router(jobs_router)
