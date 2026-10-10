"""화면 수집 요청 · PC 작업자 신호 — 관리자가 화면에서 남긴 수집 요청을 이 PC 의 작업자가 가져가 러너를 돌린다
(목표 기능 ① 수집 단추 · 2026-10-10 · 조사서 `docs/조사/러너단계결과-화면실행통로-조사.md` 안 1).

앱(컨테이너)은 수집 폴더를 읽기만 하고 러너는 PC 쪽 프로세스라, 앱이 러너를 직접 부르지 않는다. 앱과 PC 가 함께 쓰는
곳은 앱 DB 하나라 요청은 이 표에 남고, PC 작업자(`scripts/collect_worker.py`)가 매 분 와서 가져간다(Airflow · Dagster ·
GitHub 러너처럼 「웹은 요청만 남기고 실행 쪽이 가져간다」).

- 받는 값은 고르기 목록뿐 — 종류(`step` 단계 하나 · `all` 전체 수집)와 러너 단계 이름. 명령 글자는 표에 들어오지 않는다.
- 같은 대상(종류 + 단계)의 활성 줄(대기 · 도는 중)은 하나 — 부분 고유 색인이 정본이다(두 관리자가 동시에 눌러도 한 줄).
- 상태를 바꾸는 함수는 `app/services/collect_requests.py` 한 곳에 둔다(앱 API 와 PC 작업자가 같은 함수를 쓴다).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base, UUIDPkMixin


class CollectRequest(Base, UUIDPkMixin):
    __tablename__ = "collect_requests"
    __table_args__ = (
        CheckConstraint("kind IN ('step', 'all')", name="ck_collect_requests_kind"),
        CheckConstraint("(kind = 'all' AND step = '') OR (kind = 'step' AND step <> '')", name="ck_collect_requests_step"),
        CheckConstraint("status IN ('queued', 'running', 'done', 'warning', 'failed', 'rejected', 'cancelled', 'expired')",
                        name="ck_collect_requests_status"),
        # 같은 대상의 활성 줄은 하나 — 「같은 요청 한 번만」 의 정본(서비스는 이 색인에 기대어 INSERT … ON CONFLICT 로 쓴다)
        Index("ux_collect_requests_active", "kind", "step", unique=True,
              postgresql_where=text("status IN ('queued', 'running')")),
        Index("ix_collect_requests_requested_at", "requested_at"),
        {"comment": "화면 수집 요청 — 관리자가 남기고 PC 작업자가 가져가 러너를 돌린다(목표 기능 ① 수집 단추)"},
    )

    kind: Mapped[str] = mapped_column(String(8), nullable=False, comment="step = 단계 하나 · all = 전체 수집")
    step: Mapped[str] = mapped_column(String(32), nullable=False, server_default="",
                                      comment="러너 단계 이름(kind=step) · 전체 수집은 빈 글")
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="queued",
                                        comment="queued · running · done · warning · failed · rejected · cancelled · expired")
    # 탈퇴하면 줄은 남기고 이 칸만 비운다(account.DEIDENTIFY_TABLES — 감사 기록과 같은 운영 기록)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, comment="요청한 관리자")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="작업자가 가져간 시각")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker: Mapped[str] = mapped_column(String(64), nullable=False, server_default="", comment="가져간 작업자(PC 이름)")
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="러너 종료코드")
    result: Mapped[str] = mapped_column(String(300), nullable=False, server_default="", comment="결과 한 줄")
    log_path: Mapped[str] = mapped_column(String(200), nullable=False, server_default="", comment="러너 로그(저장소 기준 경로)")


class CollectWorker(Base):
    __tablename__ = "collect_workers"
    __table_args__ = (
        CheckConstraint("state IN ('idle', 'waiting', 'running')", name="ck_collect_workers_state"),
        {"comment": "PC 작업자 심장 박동 — 작업자가 매 분(도는 동안은 더 자주) 고친다. 몇 분 없으면 화면이 「꺼짐」"},
    )

    name: Mapped[str] = mapped_column(String(64), primary_key=True, comment="작업자 이름(PC 이름)")
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="이번 작업자 프로세스 시작")
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="마지막 신호")
    state: Mapped[str] = mapped_column(String(12), nullable=False, comment="idle · waiting · running")
    note: Mapped[str] = mapped_column(String(300), nullable=False, server_default="", comment="기다리는 까닭 · 도는 요청")
    allow_upload: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"),
                                               comment="올리기 단계를 받는가(작업자 등록 명령줄 --allow-upload)")
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("collect_requests.id", ondelete="SET NULL"), nullable=True,
        comment="지금 도는 요청")
