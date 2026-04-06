"""统一错误响应体（OpenAPI 与前端契约）。"""

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    """单条错误说明。"""

    code: str = Field(..., description="机器可读错误码，见 V1 基线")
    message: str = Field(..., description="人类可读说明")


class ErrorEnvelope(BaseModel):
    """所有业务/校验错误的统一外壳。"""

    error: ErrorBody
