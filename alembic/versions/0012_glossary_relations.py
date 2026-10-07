"""용어사전 — 용어 사이 관계 표 하나 (연관 개념)

Revision ID: 0012
Revises: 320128e72164
Create Date: 2026-10-02

왜
  용어사전 화면의 「연관 개념」(결정 ④ — 칩 + 헷갈리는 말의 차이 한 줄 + 작은 관계 지도)에 쓸 관계를 둔다(요구 P01-①-1 뒷절반).
  종류는 용어사전 표준 W3C SKOS 를 따른다 — related(연관) · broader(상위 · 반대 방향 하위는 읽을 때 만든다) ·
  confused_with(헷갈리는 짝 · 차이 한 줄). 설계: docs/설계/지난판/목표기능1-데이터지식-설계_v0.1.md 5.4절.

표만 만든다 — 관계는 넣지 않는다
  0011 과 같다. 관계의 원본도 용어 파일(app/services/glossary_data/terms.json · 판 2)이고 앱이 켜질 때 넣는다.

차례
  팀원 마이그레이션(320128e72164 · 모의계좌 스냅샷) 뒤에 붙인다 — 0011 뒤에 두 개가 이미 이어져 있다.

되돌리기
  표를 지운다. 관계는 파일에 있으므로 잃는 것이 없다. 단 판 2 파일을 읽는 앱은 이 표가 없으면 적재를 건너뛰고 알린다.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "320128e72164"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "glossary_relations",
        sa.Column("from_id", sa.String(60), sa.ForeignKey("glossary_terms.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("to_id", sa.String(60), sa.ForeignKey("glossary_terms.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("kind", sa.String(16), primary_key=True),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.Column("detail", sa.Text, nullable=False, server_default=""),
        sa.Column("source_code", sa.String(20), nullable=False, server_default=""),
        sa.Column("where_text", sa.String(120), nullable=False, server_default=""),
    )
    op.create_index("ix_glossary_relations_to", "glossary_relations", ["to_id"])


def downgrade() -> None:
    op.drop_index("ix_glossary_relations_to", table_name="glossary_relations")
    op.drop_table("glossary_relations")
