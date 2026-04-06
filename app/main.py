"""FastAPI 应用入口。

职责：
1) 创建 FastAPI 实例并注册路由。
2) 数据库表结构由 Alembic 迁移维护（见 docker-compose 启动命令）。
3) 托管 React 构建产物 `frontend/dist/`（Vite），路径 `/ui/`。
4) 注册全局异常处理，错误体统一为 `{"error": {"code", "message"}}`。
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.health import router as health_router
from app.api.jobs import router as jobs_router
from app.core.error_handlers import register_exception_handlers

app = FastAPI(
    title="doc-parser-service",
    version="0.1.0",
    description=(
        "错误响应统一格式：`{\"error\": {\"code\": \"...\", \"message\": \"...\"}}`。"
        "错误码见 `docs/V1-开发基线.md`（另含 HTTP 422 的 `VALIDATION_ERROR`）。"
    ),
)

register_exception_handlers(app)

app.include_router(health_router)
app.include_router(jobs_router)

_ui_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _ui_dist.is_dir() and (_ui_dist / "index.html").is_file():
    app.mount("/ui", StaticFiles(directory=str(_ui_dist), html=True), name="ui")


@app.get("/")
def root() -> RedirectResponse:
    """根路径跳转到上传页（需已执行 `npm run build` 生成 frontend/dist）。"""
    if _ui_dist.is_dir() and (_ui_dist / "index.html").is_file():
        return RedirectResponse(url="/ui/", status_code=302)
    return RedirectResponse(url="/docs", status_code=302)
