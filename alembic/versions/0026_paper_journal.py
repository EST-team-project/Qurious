"""모의투자 그림자 일지 — 판 등록 · 매 거래일 1행 · 메모 (할 일 ①-26 · 설계 `모의투자-그림자일지-설계.md` 5절).

Revision ID: 0026_paper_journal
Revises: 0025_task_ownership

표 셋 모두 추가만 한다(서비스에 고치기 · 지우기 없음). 기존 모의 장부(`orders` · `portfolio`)와 섞지 않는다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0026_paper_journal"
down_revision: Union[str, Sequence[str], None] = "0025_task_ownership"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "paper_journal_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="판 일련번호"),
        sa.Column("rule_id", sa.String(length=40), nullable=False, comment="규칙 — card_ma_cross_20_60 · auto_default"),
        sa.Column("version_no", sa.Integer(), nullable=False, comment="그 규칙의 판(1부터)"),
        sa.Column("attempt_no", sa.Integer(), nullable=False, comment="등록 때의 누적 시도 수(규칙 통틀어)"),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False, comment="등록 시각"),
        sa.Column("registered_by", sa.String(length=20), nullable=False,
                  comment="manual(등록 명령) · auto_fingerprint(지문이 바뀌어 기계가 등록)"),
        sa.Column("seal_start", sa.Date(), nullable=False, comment="봉인 시작일 — 등록 뒤 처음 마감하는 거래일"),
        sa.Column("post_hoc_from", sa.Date(), nullable=True, comment="사후 봉인 시험 첫날(판 1 만)"),
        sa.Column("post_hoc_to", sa.Date(), nullable=True, comment="사후 봉인 시험 마지막 거래일(판 1 만)"),
        sa.Column("fingerprint", sa.String(length=64), nullable=False, comment="판 지문 SHA-256(조각 지문의 묶음)"),
        sa.Column("fingerprint_parts", JSONB, nullable=False, comment="조각 이름 → 지문 앞 12자"),
        sa.Column("watch_parts", JSONB, nullable=False, comment="참고 지문 — 바뀌어도 판은 그대로(실제 자동매매 회차 코드)"),
        sa.Column("spec", JSONB, nullable=False, comment="얼린 명세 — 종목 · 판단 · 크기 · 체결 · 비용 · 판정"),
        sa.Column("code_commit", sa.String(length=40), nullable=False, comment="등록 때 git HEAD(모르면 빈 글)"),
        sa.Column("python", sa.String(length=20), nullable=False, comment="등록 때 파이썬 판"),
        sa.Column("supersedes_id", sa.Integer(), nullable=True, comment="앞 판(기계 등록 때)"),
        sa.Column("change_parts", JSONB, nullable=False, comment="앞 판과 다른 조각 이름"),
        sa.CheckConstraint("registered_by IN ('manual', 'auto_fingerprint')", name="ck_paper_journal_versions_by"),
        sa.ForeignKeyConstraint(["supersedes_id"], ["paper_journal_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_id", "version_no", name="uq_paper_journal_versions_rule_version"),
        comment="그림자 일지 규칙 판 — 등록마다 한 줄 · 추가만 (설계 5절 <표 5-1>)",
    )
    op.create_table(
        "paper_journal_days",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="행 일련번호"),
        sa.Column("version_id", sa.Integer(), nullable=False, comment="판"),
        sa.Column("trade_date", sa.Date(), nullable=False, comment="거래일 D"),
        sa.Column("grade", sa.String(length=10), nullable=False, comment="post_hoc(사후 봉인 시험) · forward(전진 · 봉인)"),
        sa.Column("status", sa.String(length=10), nullable=False, comment="ok · partial(자료 없는 종목이 있음)"),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, comment="계산 시각"),
        sa.Column("recomputed", sa.Boolean(), nullable=False, comment="예정(다음 거래일)보다 늦게 계산한 전진 행 — 값은 같다"),
        sa.Column("data_as_of", sa.Date(), nullable=False, comment="판단에 쓴 마지막 봉 날짜"),
        sa.Column("code_commit", sa.String(length=40), nullable=False, comment="계산 때 git HEAD"),
        sa.Column("fingerprint", sa.String(length=64), nullable=False, comment="계산 때 판 지문(판의 지문과 같아야 함)"),
        sa.Column("fills", JSONB, nullable=False, comment="앞 행 주문의 그날 시가 가상 체결"),
        sa.Column("decisions", JSONB, nullable=False, comment="그날 종가까지의 판단(대상 종목)"),
        sa.Column("ranking", JSONB, nullable=False, comment="기본 규칙의 31종목 점수(카드는 빈 목록)"),
        sa.Column("orders", JSONB, nullable=False, comment="다음 거래일 시가 주문"),
        sa.Column("skipped", JSONB, nullable=False, comment="크기 셈에서 빠진 주문과 까닭"),
        sa.Column("cash", sa.Float(), nullable=False, comment="그날 끝 현금(원)"),
        sa.Column("positions", JSONB, nullable=False, comment="보유 — 종목 → 수량 · 평균 단가 · 종가 · 평가액"),
        sa.Column("equity", sa.Float(), nullable=False, comment="그날 종가 평가액(원)"),
        sa.Column("day_return", sa.Float(), nullable=False, comment="앞 행 평가액 대비 수익률"),
        sa.Column("flags", JSONB, nullable=False, comment="일손실 한도 · 조정 사건 · 참고 지문 바뀜 표시"),
        sa.CheckConstraint("grade IN ('post_hoc', 'forward')", name="ck_paper_journal_days_grade"),
        sa.CheckConstraint("status IN ('ok', 'partial')", name="ck_paper_journal_days_status"),
        sa.ForeignKeyConstraint(["version_id"], ["paper_journal_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_id", "trade_date", name="uq_paper_journal_days_version_date"),
        comment="그림자 일지 — 판마다 거래일 하루 한 행 · 시가 체결 → 종가 평가 → 다음 판단 · 추가만 (설계 2 · 5절)",
    )
    op.create_index("ix_paper_journal_days_trade_date", "paper_journal_days", ["trade_date"])
    op.create_table(
        "paper_journal_notes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="메모 일련번호"),
        sa.Column("version_id", sa.Integer(), nullable=True, comment="판(빈칸 가능)"),
        sa.Column("trade_date", sa.Date(), nullable=True, comment="거래일(빈칸 가능)"),
        sa.Column("kind", sa.String(length=20), nullable=False,
                  comment="opening · change_reason · judgment · interpretation · ops"),
        sa.Column("author", sa.String(length=40), nullable=False, comment="쓴 사람 · 기계(journal)"),
        sa.Column("written_at", sa.DateTime(timezone=True), nullable=False, comment="쓴 시각"),
        sa.Column("text", sa.Text(), nullable=False, comment="글"),
        sa.CheckConstraint("kind IN ('opening', 'change_reason', 'judgment', 'interpretation', 'ops')",
                           name="ck_paper_journal_notes_kind"),
        sa.ForeignKeyConstraint(["version_id"], ["paper_journal_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        comment="그림자 일지 메모 — 개봉 기록 · 판 바뀜 까닭 · 판정 범위 · 사람 해석 · 운영 · 추가만 (설계 5절 <표 5-3>)",
    )


def downgrade() -> None:
    op.drop_table("paper_journal_notes")
    op.drop_index("ix_paper_journal_days_trade_date", table_name="paper_journal_days")
    op.drop_table("paper_journal_days")
    op.drop_table("paper_journal_versions")
