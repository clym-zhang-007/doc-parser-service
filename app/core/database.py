"""数据库连接与会话（ORM 模型见 app.core.models）。"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.models import Job  # re-export for existing imports

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://doc_parser:doc_parser@postgres:5432/doc_parser",
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """提供数据库会话的依赖注入生成器。

    Yields:
        Session: 当前请求可用的数据库会话。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
