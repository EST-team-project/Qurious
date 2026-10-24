"""모의투자 그림자 일지 — 판 등록 · 매 거래일 1행 · 사람 메모 (할 일 ①-26 · 설계 `모의투자-그림자일지-설계.md` 5절).

쓰는 곳: `scripts/paper_journal.py` → `app.services.paper_journal`(12:30 러너 `journal` 단계). 읽는 곳: HF 원장 내보내기 · 판정.

세 표 모두 **추가만** 한다 — 서비스에 고치기 · 지우기 함수가 없다(TC-PJ). 판이 바뀌면 옛 판 줄을 고치지 않고 새 판 줄을 더한다
(`supersedes_id`). 사람이 붙이는 까닭 · 해석은 판 · 행 줄이 아니라 메모 표에 더한다. 기존 모의 장부(`orders` · `portfolio`)와
섞지 않는다 — 회전율 · 계좌 초기화 · 100일 백테스트 주문과 섞이면 판정할 수 없다(결정 대장 2026-10-23).
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PaperJournalVersion(Base):
    __tablename__ = "paper_journal_versions"
    __table_args__ = (
        UniqueConstraint("rule_id", "version_no", name="uq_paper_journal_versions_rule_version"),
        CheckConstraint("registered_by IN ('manual', 'auto_fingerprint')", name="ck_paper_journal_versions_by"),
        {"comment": "그림자 일지 규칙 판 — 등록마다 한 줄 · 추가만 (설계 5절 <표 5-1>)"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="판 일련번호")
    rule_id: Mapped[str] = mapped_column(String(40), nullable=False, comment="규칙 — card_ma_cross_20_60 · auto_default")
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="그 규칙의 판(1부터)")
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="등록 때의 누적 시도 수(규칙 통틀어)")
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="등록 시각")
    registered_by: Mapped[str] = mapped_column(String(20), nullable=False,
                                               comment="manual(등록 명령) · auto_fingerprint(지문이 바뀌어 기계가 등록)")
    seal_start: Mapped[date] = mapped_column(Date, nullable=False, comment="봉인 시작일 — 등록 뒤 처음 마감하는 거래일")
    post_hoc_from: Mapped[date | None] = mapped_column(Date, comment="사후 봉인 시험 첫날(판 1 만)")
    post_hoc_to: Mapped[date | None] = mapped_column(Date, comment="사후 봉인 시험 마지막 거래일(판 1 만)")
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, comment="판 지문 SHA-256(조각 지문의 묶음)")
    fingerprint_parts: Mapped[dict] = mapped_column(JSONB, nullable=False, comment="조각 이름 → 지문 앞 12자")
    watch_parts: Mapped[dict] = mapped_column(JSONB, nullable=False,
                                              comment="참고 지문 — 바뀌어도 판은 그대로(실제 자동매매 회차 코드)")
    spec: Mapped[dict] = mapped_column(JSONB, nullable=False, comment="얼린 명세 — 종목 · 판단 · 크기 · 체결 · 비용 · 판정")
    code_commit: Mapped[str] = mapped_column(String(40), nullable=False, comment="등록 때 git HEAD(모르면 빈 글)")
    python: Mapped[str] = mapped_column(String(20), nullable=False, comment="등록 때 파이썬 판")
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("paper_journal_versions.id"), comment="앞 판(기계 등록 때)")
    change_parts: Mapped[list] = mapped_column(JSONB, nullable=False, comment="앞 판과 다른 조각 이름")


class PaperJournalDay(Base):
    __tablename__ = "paper_journal_days"
    __table_args__ = (
        UniqueConstraint("version_id", "trade_date", name="uq_paper_journal_days_version_date"),
        CheckConstraint("grade IN ('post_hoc', 'forward')", name="ck_paper_journal_days_grade"),
        CheckConstraint("status IN ('ok', 'partial')", name="ck_paper_journal_days_status"),
        Index("ix_paper_journal_days_trade_date", "trade_date"),
        {"comment": "그림자 일지 — 판마다 거래일 하루 한 행 · 시가 체결 → 종가 평가 → 다음 판단 · 추가만 (설계 2 · 5절)"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="행 일련번호")
    version_id: Mapped[int] = mapped_column(ForeignKey("paper_journal_versions.id"), nullable=False, comment="판")
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, comment="거래일 D")
    grade: Mapped[str] = mapped_column(String(10), nullable=False, comment="post_hoc(사후 봉인 시험) · forward(전진 · 봉인)")
    status: Mapped[str] = mapped_column(String(10), nullable=False, comment="ok · partial(자료 없는 종목이 있음)")
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="계산 시각")
    recomputed: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                             comment="예정(다음 거래일)보다 늦게 계산한 전진 행 — 값은 같다")
    data_as_of: Mapped[date] = mapped_column(Date, nullable=False, comment="판단에 쓴 마지막 봉 날짜")
    code_commit: Mapped[str] = mapped_column(String(40), nullable=False, comment="계산 때 git HEAD")
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, comment="계산 때 판 지문(판의 지문과 같아야 함)")
    fills: Mapped[list] = mapped_column(JSONB, nullable=False, comment="앞 행 주문의 그날 시가 가상 체결")
    decisions: Mapped[list] = mapped_column(JSONB, nullable=False, comment="그날 종가까지의 판단(대상 종목)")
    ranking: Mapped[list] = mapped_column(JSONB, nullable=False, comment="기본 규칙의 31종목 점수(카드는 빈 목록)")
    orders: Mapped[list] = mapped_column(JSONB, nullable=False, comment="다음 거래일 시가 주문")
    skipped: Mapped[list] = mapped_column(JSONB, nullable=False, comment="크기 셈에서 빠진 주문과 까닭")
    cash: Mapped[float] = mapped_column(Float, nullable=False, comment="그날 끝 현금(원)")
    positions: Mapped[dict] = mapped_column(JSONB, nullable=False, comment="보유 — 종목 → 수량 · 평균 단가 · 종가 · 평가액")
    equity: Mapped[float] = mapped_column(Float, nullable=False, comment="그날 종가 평가액(원)")
    day_return: Mapped[float] = mapped_column(Float, nullable=False, comment="앞 행 평가액 대비 수익률")
    flags: Mapped[list] = mapped_column(JSONB, nullable=False, comment="일손실 한도 · 조정 사건 · 참고 지문 바뀜 표시")


class PaperJournalNote(Base):
    __tablename__ = "paper_journal_notes"
    __table_args__ = (
        CheckConstraint("kind IN ('opening', 'change_reason', 'judgment', 'interpretation', 'ops')",
                        name="ck_paper_journal_notes_kind"),
        {"comment": "그림자 일지 메모 — 개봉 기록 · 판 바뀜 까닭 · 판정 범위 · 사람 해석 · 운영 · 추가만 (설계 5절 <표 5-3>)"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="메모 일련번호")
    version_id: Mapped[int | None] = mapped_column(ForeignKey("paper_journal_versions.id"), comment="판(빈칸 가능)")
    trade_date: Mapped[date | None] = mapped_column(Date, comment="거래일(빈칸 가능)")
    kind: Mapped[str] = mapped_column(String(20), nullable=False,
                                      comment="opening · change_reason · judgment · interpretation · ops")
    author: Mapped[str] = mapped_column(String(40), nullable=False, comment="쓴 사람 · 기계(journal)")
    written_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="쓴 시각")
    text: Mapped[str] = mapped_column(Text, nullable=False, comment="글")
