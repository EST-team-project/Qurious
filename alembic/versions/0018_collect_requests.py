"""화면 수집 요청 · PC 작업자 신호 — 표 둘 (목표 기능 ① 수집 단추 · 2026-10-10).

관리자가 화면에서 남긴 수집 요청을 이 PC 의 작업자가 가져가 러너를 돌린다(조사서
`docs/조사/러너단계결과-화면실행통로-조사.md` 안 1).

Revision ID: 0018
Revises: 0017

표 둘을 새로 더하기만 한다(남의 표는 건드리지 않는다). 같은 대상(종류 + 단계)의 활성 줄(대기 · 도는 중)은 하나 —
부분 고유 색인 `ux_collect_requests_active` 가 「같은 요청 한 번만」 의 정본이다. 요청자 칸은 탈퇴하면 비운다(SET NULL).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: Union[str, Sequence[str], None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "collect_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False, comment="step = 단계 하나 · all = 전체 수집"),
        sa.Column("step", sa.String(length=32), server_default="", nullable=False,
                  comment="러너 단계 이름(kind=step) · 전체 수집은 빈 글"),
        sa.Column("status", sa.String(length=12), server_default="queued", nullable=False,
                  comment="queued · running · done · warning · failed · rejected · cancelled · expired"),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=True, comment="요청한 관리자"),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True, comment="작업자가 가져간 시각"),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker", sa.String(length=64), server_default="", nullable=False, comment="가져간 작업자(PC 이름)"),
        sa.Column("exit_code", sa.Integer(), nullable=True, comment="러너 종료코드"),
        sa.Column("result", sa.String(length=300), server_default="", nullable=False, comment="결과 한 줄"),
        sa.Column("log_path", sa.String(length=200), server_default="", nullable=False, comment="러너 로그(저장소 기준 경로)"),
        sa.CheckConstraint("kind IN ('step', 'all')", name="ck_collect_requests_kind"),
        sa.CheckConstraint("(kind = 'all' AND step = '') OR (kind = 'step' AND step <> '')", name="ck_collect_requests_step"),
        sa.CheckConstraint("status IN ('queued', 'running', 'done', 'warning', 'failed', 'rejected', 'cancelled', 'expired')",
                           name="ck_collect_requests_status"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        comment="화면 수집 요청 — 관리자가 남기고 PC 작업자가 가져가 러너를 돌린다(목표 기능 ① 수집 단추)",
    )
    op.create_index("ux_collect_requests_active", "collect_requests", ["kind", "step"], unique=True,
                    postgresql_where=sa.text("status IN ('queued', 'running')"))
    op.create_index("ix_collect_requests_requested_at", "collect_requests", ["requested_at"])
    op.create_table(
        "collect_workers",
        sa.Column("name", sa.String(length=64), nullable=False, comment="작업자 이름(PC 이름)"),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, comment="이번 작업자 프로세스 시작"),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False, comment="마지막 신호"),
        sa.Column("state", sa.String(length=12), nullable=False, comment="idle · waiting · running"),
        sa.Column("note", sa.String(length=300), server_default="", nullable=False, comment="기다리는 까닭 · 도는 요청"),
        sa.Column("allow_upload", sa.Boolean(), server_default=sa.text("false"), nullable=False,
                  comment="올리기 단계를 받는가(작업자 등록 명령줄 --allow-upload)"),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=True, comment="지금 도는 요청"),
        sa.CheckConstraint("state IN ('idle', 'waiting', 'running')", name="ck_collect_workers_state"),
        sa.ForeignKeyConstraint(["request_id"], ["collect_requests.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("name"),
        comment="PC 작업자 심장 박동 — 작업자가 매 분(도는 동안은 더 자주) 고친다. 몇 분 없으면 화면이 「꺼짐」",
    )


def downgrade() -> None:
    op.drop_table("collect_workers")
    op.drop_index("ix_collect_requests_requested_at", table_name="collect_requests")
    op.drop_index("ux_collect_requests_active", table_name="collect_requests", postgresql_where=sa.text("status IN ('queued', 'running')"))
    op.drop_table("collect_requests")
