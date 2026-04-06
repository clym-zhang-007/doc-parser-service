"""作业（文档解析任务）相关路由。"""

from datetime import datetime
import json
from uuid import uuid4

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.core.database import Job, get_db
from app.core.errors import ApiError, ErrorCode
from app.schemas import JobResponse, JobResultResponse, JobStatusResponse
from app.schemas.errors import ErrorEnvelope
from app.services.storage import save_job_upload
from app.workers.celery_app import celery_app, parse_document

router = APIRouter(
    prefix="/v1",
    tags=["jobs"],
    responses={
        400: {"model": ErrorEnvelope, "description": "请求不合法"},
        404: {"model": ErrorEnvelope, "description": "任务不存在"},
        409: {"model": ErrorEnvelope, "description": "结果尚未就绪"},
        413: {"model": ErrorEnvelope, "description": "文件过大"},
        415: {"model": ErrorEnvelope, "description": "不支持的文件类型"},
        422: {"model": ErrorEnvelope, "description": "参数校验失败"},
        500: {"model": ErrorEnvelope, "description": "服务器内部错误"},
    },
)


def _format_dt(value: datetime | None) -> str | None:
    """将 datetime 统一转为 ISO8601 字符串。"""
    if not value:
        return None
    return value.isoformat()


@router.post("/jobs", response_model=JobResponse)
async def create_job(
    file: UploadFile = File(..., description="待解析文档（.pdf / .docx / .txt / .md）"),
    db: Session = Depends(get_db),
) -> JobResponse:
    """创建解析任务：保存上传文件到 `storage/`，再异步投递 Celery。"""
    job_id = str(uuid4())
    storage_path, file_name, file_type = await save_job_upload(job_id, file)

    job = Job(
        id=job_id,
        file_name=file_name,
        file_type=file_type,
        storage_path=storage_path,
        status="queued",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    parse_document.delay(job_id)

    return JobResponse(
        job_id=job.id,
        status=job.status,
        created_at=_format_dt(job.created_at) or "",
    )


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str, db: Session = Depends(get_db)) -> JobStatusResponse:
    """查询任务当前状态。"""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise ApiError(ErrorCode.JOB_NOT_FOUND, "job not found", status_code=404)

    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        created_at=_format_dt(job.created_at) or "",
        updated_at=_format_dt(job.updated_at),
    )


@router.get("/jobs/{job_id}/result", response_model=JobResultResponse)
def get_job_result(job_id: str, db: Session = Depends(get_db)) -> JobResultResponse:
    """查询任务结果；未完成返回 409 RESULT_NOT_READY。成功/失败返回 200 与 result/error 字段。"""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise ApiError(ErrorCode.JOB_NOT_FOUND, "job not found", status_code=404)

    if job.status in ("queued", "running"):
        raise ApiError(
            ErrorCode.RESULT_NOT_READY,
            "result is not ready yet; poll job status until success or failed",
            status_code=409,
        )

    parsed_result = None
    if job.result_json:
        try:
            parsed_result = json.loads(job.result_json)
        except json.JSONDecodeError:
            parsed_result = {"raw": job.result_json}

    if job.status == "success" and parsed_result is None:
        async_result = celery_app.AsyncResult(job_id)
        if async_result.successful():
            parsed_result = async_result.result

    return JobResultResponse(
        job_id=job.id,
        status=job.status,
        result=parsed_result,
        error=job.error_message,
    )
