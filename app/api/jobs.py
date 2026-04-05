"""作业（文档解析任务）相关路由。"""

from datetime import datetime
import json
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.database import Job, get_db
from app.schemas import JobResponse, JobResultResponse, JobStatusResponse
from app.services.storage import save_job_upload
from app.workers.celery_app import celery_app, parse_document

router = APIRouter(prefix="/v1", tags=["jobs"])


def _format_dt(value: datetime | None) -> str | None:
    """将 datetime 统一转为 ISO8601 字符串。

    Args:
        value: 待转换的 datetime，允许为 None。

    Returns:
        str | None: ISO8601 字符串；若输入为空则返回 None。
    """
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
    """查询任务当前状态。

    Args:
        job_id: 任务 ID。
        db: FastAPI 注入的数据库会话。

    Returns:
        JobStatusResponse: 包含状态与时间戳信息。
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="job not found")

    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        created_at=_format_dt(job.created_at) or "",
        updated_at=_format_dt(job.updated_at),
    )


@router.get("/jobs/{job_id}/result", response_model=JobResultResponse)
def get_job_result(job_id: str, db: Session = Depends(get_db)) -> JobResultResponse:
    """查询任务结果；若数据库未命中则回退查询 Celery 后端。

    Args:
        job_id: 任务 ID。
        db: FastAPI 注入的数据库会话。

    Returns:
        JobResultResponse: 包含 status/result/error 的结果对象。
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="job not found")

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
