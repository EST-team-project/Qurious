"""용어사전 — 분류 · 자료 원천 · 용어 · 별칭 · 적재 이력 (표 다섯)

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-30

왜
  화면의 용어 설명이 자바스크립트 상수 55개뿐이라 검색 · 분류 · 출처 · 다른 화면에서의 재사용이 안 됐다.
  통합본(rag-lab/)의 용어집 글과 합친 용어 수백 개를 서버가 돌려주도록 표를 만든다(요구 P01-①-1).

표만 만든다 — 용어는 넣지 않는다
  용어의 원본은 파일(app/services/glossary_data/terms.json)이고 앱이 켜질 때 표에 넣는다(app/services/glossary.py).
  용어를 고칠 때마다 마이그레이션을 새로 쓰지 않으려는 것이다. Alembic 은 스키마용이고, 데이터 이전을 스키마 판에
  묶는 것은 권하지 않는다(Alembic Cookbook 「Data Migrations」).
  그래서 이 마이그레이션 직후에는 표가 비어 있고, 앱이 한 번 켜지면 찬다.

되돌리기
  표 다섯을 지운다. 용어는 파일에 있으므로 잃는 것이 없다(다시 올리면 앱이 다시 넣는다).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "glossary_categories",
        sa.Column("code", sa.String(20), primary_key=True),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("description", sa.String(200), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_table(
        "glossary_sources",
        sa.Column("code", sa.String(20), primary_key=True),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("origin", sa.String(200), nullable=False, server_default=""),
        sa.Column("paths", sa.String(300), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_table(
        "glossary_terms",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("term", sa.String(80), nullable=False),
        sa.Column("english", sa.String(120), nullable=False, server_default=""),
        sa.Column("hanja", sa.String(60), nullable=False, server_default=""),
        sa.Column("category_code", sa.String(20), sa.ForeignKey("glossary_categories.code"), nullable=False),
        sa.Column("lead_source_code", sa.String(20), sa.ForeignKey("glossary_sources.code"), nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("definition", sa.Text, nullable=False, server_default=""),
        sa.Column("example", sa.Text, nullable=False, server_default=""),
        sa.Column("caution", sa.Text, nullable=False, server_default=""),
        sa.Column("formula", sa.String(200), nullable=False, server_default=""),
        sa.Column("origin_note", sa.Text, nullable=False, server_default=""),
        sa.Column("app_note", sa.Text, nullable=False, server_default=""),
        sa.Column("source_codes", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("notes", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("sort_key", sa.String(80), nullable=False),
        sa.Column("chosung", sa.String(80), nullable=False, server_default=""),
        sa.Column("name_text", sa.Text, nullable=False, server_default=""),
        sa.Column("body_text", sa.Text, nullable=False, server_default=""),
    )
    op.create_index("ix_glossary_terms_category", "glossary_terms", ["category_code", "sort_key"])
    op.create_table(
        "glossary_aliases",
        sa.Column("alias_norm", sa.String(120), primary_key=True),
        sa.Column("term_id", sa.String(60), sa.ForeignKey("glossary_terms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alias", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
    )
    op.create_index("ix_glossary_aliases_term", "glossary_aliases", ["term_id"])
    op.create_table(
        "glossary_loads",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("rows_checksum", sa.String(64), nullable=False),
        sa.Column("format_version", sa.Integer, nullable=False),
        sa.Column("term_count", sa.Integer, nullable=False),
        sa.Column("alias_count", sa.Integer, nullable=False),
        sa.Column("category_count", sa.Integer, nullable=False),
        sa.Column("source_count", sa.Integer, nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("glossary_loads")
    op.drop_index("ix_glossary_aliases_term", table_name="glossary_aliases")
    op.drop_table("glossary_aliases")
    op.drop_index("ix_glossary_terms_category", table_name="glossary_terms")
    op.drop_table("glossary_terms")
    op.drop_table("glossary_sources")
    op.drop_table("glossary_categories")
