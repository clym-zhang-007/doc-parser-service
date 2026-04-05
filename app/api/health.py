"""健康检查路由。"""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """服务健康检查接口。

    Returns:
        dict[str, str]: 固定返回 {"status": "ok"}。
    """
    return {"status": "ok"}
