"""initial jobs table

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-03

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("file_name", sa.String(), nullable=True),
        sa.Column("file_type", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_jobs_file_name"), "jobs", ["file_name"], unique=False)
    op.create_index(op.f("ix_jobs_id"), "jobs", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_jobs_id"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_file_name"), table_name="jobs")
    op.drop_table("jobs")
