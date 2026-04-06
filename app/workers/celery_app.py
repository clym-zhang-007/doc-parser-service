"""Celery Worker 与异步任务定义模块。

职责：
1) 初始化 Celery 应用（broker/backend）。
2) 定义健康检查任务与文档解析任务。
3) 维护任务状态流转并持久化处理结果。
"""

import json
import logging

from celery import Celery

from app.core.database import Job, SessionLocal
from app.services.document_parse import build_error_result, parse_stored_file
from app.services.storage import absolute_path

logger = logging.getLogger(__name__)

celery_app = Celery(
    "document_parser",
    broker="redis://redis:6379/0",
    backend="redis://redis:6379/0",
)


@celery_app.task(name="health.ping")
def ping() -> str:
    """Worker 健康检查任务。"""
    return "pong"


@celery_app.task(name="jobs.parse_document", bind=True)
def parse_document(self, job_id: str) -> dict:
    """执行文档解析：读本地存储文件，LlamaIndex 抽取文本，写入基线结构 result_json。"""
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise ValueError(f"job not found: {job_id}")

        job.status = "running"
        db.commit()

        path = absolute_path(job.storage_path)
        if path is None or not path.is_file():
            err = build_error_result(
                code="PARSE_FAILED",
                message="stored file missing or path invalid",
                file_type=job.file_type,
                file_name=job.file_name,
                storage_path=job.storage_path,
            )
            job.status = "failed"
            job.error_message = "PARSE_FAILED: stored file missing or path invalid"
            job.result_json = json.dumps(err, ensure_ascii=False)
            db.commit()
            raise FileNotFoundError(job.storage_path)

        try:
            result = parse_stored_file(
                path=path,
                file_type=job.file_type or "",
                file_name=job.file_name,
                storage_path=job.storage_path,
            )
        except Exception as exc:
            logger.exception("parse failed job_id=%s", job_id)
            err = build_error_result(
                code="PARSE_FAILED",
                message=str(exc),
                file_type=job.file_type,
                file_name=job.file_name,
                storage_path=job.storage_path,
            )
            job.status = "failed"
            job.error_message = f"PARSE_FAILED: {exc}"
            job.result_json = json.dumps(err, ensure_ascii=False)
            db.commit()
            raise

        job.status = "success"
        job.error_message = None
        job.result_json = json.dumps(result, ensure_ascii=False)
        db.commit()
        return result
    except Exception as exc:
        job2 = db.query(Job).filter(Job.id == job_id).first()
        if job2 and job2.status == "running":
            err = build_error_result(
                code="PARSE_FAILED",
                message=str(exc),
                file_type=job2.file_type,
                file_name=job2.file_name,
                storage_path=job2.storage_path,
            )
            job2.status = "failed"
            job2.error_message = f"PARSE_FAILED: {exc}"
            job2.result_json = json.dumps(err, ensure_ascii=False)
            db.commit()
        raise
    finally:
        db.close()
