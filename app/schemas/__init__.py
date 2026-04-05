"""Pydantic 请求/响应模型（API 合同）。

职责：
1) 定义 API 输入校验模型。
2) 定义 API 输出序列化模型。
3) 确保前后端字段语义一致。
"""

from typing import Optional

from pydantic import BaseModel


class JobResponse(BaseModel):
    """创建任务接口响应。

    Attributes:
        job_id: 新建任务唯一标识。
        status: 初始状态（通常为 queued）。
        created_at: 任务创建时间（ISO8601 字符串）。
    """

    job_id: str
    status: str
    created_at: str


class JobStatusResponse(BaseModel):
    """任务状态查询接口响应。

    Attributes:
        job_id: 任务唯一标识。
        status: 当前任务状态。
        created_at: 任务创建时间。
        updated_at: 最近更新时间（可能为空）。
    """

    job_id: str
    status: str
    created_at: str
    updated_at: Optional[str] = None


class JobResultResponse(BaseModel):
    """任务结果查询接口响应。

    Attributes:
        job_id: 任务唯一标识。
        status: 当前任务状态。
        result: 成功时的结构化结果，失败/未完成时可为空。
        error: 失败时的错误信息，成功时通常为空。
    """

    job_id: str
    status: str
    result: Optional[dict] = None
    error: Optional[str] = None
