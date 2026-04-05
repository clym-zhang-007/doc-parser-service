"""add jobs.storage_path for uploaded file location

Revision ID: 0002_storage
Revises: 0001_initial
Create Date: 2026-04-04

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "0002_storage"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _jobs_column_names(connection) -> set[str]:
    return {c["name"] for c in inspect(connection).get_columns("jobs")}


def upgrade() -> None:
    # 幂等：避免 api/worker 曾并行跑迁移时「列已存在」导致失败。
    conn = op.get_bind()
    if "storage_path" not in _jobs_column_names(conn):
        op.add_column("jobs", sa.Column("storage_path", sa.String(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    if "storage_path" in _jobs_column_names(conn):
        op.drop_column("jobs", "storage_path")
