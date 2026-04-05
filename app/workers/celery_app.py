"""Celery Worker 与异步任务定义模块。

职责：
1) 初始化 Celery 应用（broker/backend）。
2) 定义健康检查任务与文档解析任务。
3) 维护任务状态流转并持久化处理结果。
"""

from celery import Celery
import json

from app.core.database import Job, SessionLocal
from app.services.storage import absolute_path

# broker: 任务队列（消息中转）；backend: 任务结果存储。
celery_app = Celery(
    "document_parser",
    broker="redis://redis:6379/0",
    backend="redis://redis:6379/0",
)


@celery_app.task(name="health.ping")
def ping() -> str:
    """Worker 健康检查任务。

    Returns:
        str: 固定返回 "pong"。
    """
    return "pong"


@celery_app.task(name="jobs.parse_document", bind=True)
def parse_document(self, job_id: str) -> dict:
    """执行文档解析任务并回写状态到数据库。

    Args:
        self: Celery 绑定任务实例（当前实现未使用）。
        job_id: 任务 ID（由 API 层创建并传入）。

    Returns:
        dict: 解析结果字典。

    Raises:
        ValueError: 当 job_id 不存在时抛出。
        Exception: 解析过程中的其他异常会继续上抛给 Celery。
    """
    # Worker 内部独立创建数据库会话，不复用 API 请求会话。
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise ValueError(f"job not found: {job_id}")

        # 状态流转：queued -> running。
        job.status = "running"
        db.commit()

        path = absolute_path(job.storage_path)
        file_exists = path is not None and path.is_file()

        # V1 先提供最小可用占位结果，后续替换为真实解析流程（读 path）。
        result = {
            "summary": f"parsed {job.file_name}",
            "file_type": job.file_type,
            "storage_path": job.storage_path,
            "file_exists": file_exists,
            "text_length": 0,
        }
        # 状态流转：running -> success，并写入可持久化结果。
        job.status = "success"
        job.error_message = None
        job.result_json = json.dumps(result, ensure_ascii=False)
        db.commit()
        return result
    except Exception as exc:
        # 状态流转：running -> failed，并记录错误上下文。
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = "failed"
            job.error_message = str(exc)
            db.commit()
        raise
    finally:
        # 无论成功或失败，都关闭会话释放连接。
        db.close()
