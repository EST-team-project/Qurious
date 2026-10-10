"""화면 수집 요청에 「빠진 날 채우기」 — 종류 fill · 날짜 칸 둘 (2026-10-10 · 사용자 결정 — 새 요청 종류 fill · 상한 31일).

앱 DB 가 꺼져 신호 단계가 건너뛴 거래일을 화면에서 채운다. 러너가 빠진 날(첫날 · 마지막 날)을 적고, 화면은 그 두 날짜를 그대로
요청 줄에 남기며, PC 작업자가 `daily_update.py run --fill <단계> --from --to` 로 돌린다.

Revision ID: 0019
Revises: 0018

이 표만 고친다(남의 표는 건드리지 않는다).
- 날짜 칸 둘(`date_from` · `date_to` · 둘 다 비울 수 있다 — 채우기 줄에만 쓴다)
- 종류 CHECK 에 fill · 단계 CHECK 에 「fill 도 단계 이름이 있다」
- 날짜 CHECK — 채우기에는 날짜 둘(첫날 ≤ 마지막 날) · 다른 종류에는 날짜 없음(서비스를 거치지 않은 줄도 막는다)
같은 대상의 활성 줄 하나(부분 고유 색인 `ux_collect_requests_active` · 종류 + 단계)는 그대로다 — 같은 단계의 채우기는 하나씩 돈다.

되돌리면(downgrade) 채우기 줄을 지운다 — 옛 CHECK 가 fill 줄을 받지 않는다. 운영 기록이 줄지만 감사 줄(`audit_events`)은 남는다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0019"
down_revision: Union[str, Sequence[str], None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DATES_CHECK = ("(kind = 'fill' AND date_from IS NOT NULL AND date_to IS NOT NULL AND date_from <= date_to) OR "
               "(kind <> 'fill' AND date_from IS NULL AND date_to IS NULL)")


def upgrade() -> None:
    op.add_column("collect_requests", sa.Column("date_from", sa.Date(), nullable=True,
                                                comment="빠진 날 채우기의 첫날(kind=fill · 양 끝 포함)"))
    op.add_column("collect_requests", sa.Column("date_to", sa.Date(), nullable=True,
                                                comment="빠진 날 채우기의 마지막 날(kind=fill)"))
    op.drop_constraint("ck_collect_requests_kind", "collect_requests", type_="check")
    op.create_check_constraint("ck_collect_requests_kind", "collect_requests", "kind IN ('step', 'all', 'fill')")
    op.drop_constraint("ck_collect_requests_step", "collect_requests", type_="check")
    op.create_check_constraint("ck_collect_requests_step", "collect_requests",
                               "(kind = 'all' AND step = '') OR (kind IN ('step', 'fill') AND step <> '')")
    op.create_check_constraint("ck_collect_requests_dates", "collect_requests", DATES_CHECK)
    op.alter_column("collect_requests", "kind", existing_type=sa.String(length=8), existing_nullable=False,
                    comment="step = 단계 하나 · all = 전체 수집 · fill = 빠진 날 채우기",
                    existing_comment="step = 단계 하나 · all = 전체 수집")
    op.alter_column("collect_requests", "step", existing_type=sa.String(length=32), existing_nullable=False,
                    existing_server_default="", comment="러너 단계 이름(kind=step · fill) · 전체 수집은 빈 글",
                    existing_comment="러너 단계 이름(kind=step) · 전체 수집은 빈 글")


def downgrade() -> None:
    op.execute("DELETE FROM collect_requests WHERE kind = 'fill'")
    op.alter_column("collect_requests", "step", existing_type=sa.String(length=32), existing_nullable=False,
                    existing_server_default="", comment="러너 단계 이름(kind=step) · 전체 수집은 빈 글",
                    existing_comment="러너 단계 이름(kind=step · fill) · 전체 수집은 빈 글")
    op.alter_column("collect_requests", "kind", existing_type=sa.String(length=8), existing_nullable=False,
                    comment="step = 단계 하나 · all = 전체 수집",
                    existing_comment="step = 단계 하나 · all = 전체 수집 · fill = 빠진 날 채우기")
    op.drop_constraint("ck_collect_requests_dates", "collect_requests", type_="check")
    op.drop_constraint("ck_collect_requests_step", "collect_requests", type_="check")
    op.create_check_constraint("ck_collect_requests_step", "collect_requests",
                               "(kind = 'all' AND step = '') OR (kind = 'step' AND step <> '')")
    op.drop_constraint("ck_collect_requests_kind", "collect_requests", type_="check")
    op.create_check_constraint("ck_collect_requests_kind", "collect_requests", "kind IN ('step', 'all')")
    op.drop_column("collect_requests", "date_to")
    op.drop_column("collect_requests", "date_from")
