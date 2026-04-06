"""API 业务异常与 V1 错误码常量（对齐 docs/V1-开发基线.md）。"""


class ErrorCode:
    """与基线「统一错误码」一致；VALIDATION_ERROR 为 HTTP 422 补充。"""

    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    RESULT_NOT_READY = "RESULT_NOT_READY"
    PARSE_FAILED = "PARSE_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"


class ApiError(Exception):
    """抛出后由全局处理器序列化为统一 JSON。"""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)
