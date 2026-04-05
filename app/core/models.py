"""SQLAlchemy ORM 模型（不含 engine，便于 Alembic 仅加载 metadata）。"""

from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Job(Base):
    """文档解析任务模型（映射到 jobs 表）。

    字段说明：
    - id: 任务唯一标识（UUID 字符串）
    - file_name/file_type: 输入文档元信息
    - status: queued/running/success/failed
    - created_at/updated_at: 创建与更新时间戳
    - error_message: 失败原因（失败时写入）
    - result_json: 解析结果 JSON 文本（成功时写入）
    - storage_path: 相对 STORAGE_ROOT 的落盘路径（如 uploads/{job_id}/xxx.pdf）
    """

    __tablename__ = "jobs"

    id = Column(String, primary_key=True, index=True)
    file_name = Column(String, index=True)
    file_type = Column(String)
    storage_path = Column(String, nullable=True)
    status = Column(String, default="queued")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    error_message = Column(String, nullable=True)
    result_json = Column(Text, nullable=True)
