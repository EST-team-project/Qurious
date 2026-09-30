"""용어사전 — 분류 · 자료 원천 · 용어 · 별칭 · 적재 이력.

이 표들은 **파일의 사본**이다. 원본은 `app/services/glossary_data/terms.json`(git 으로 판 관리)이고,
앱이 켜질 때 넣을 내용이 마지막 적재와 다르면 다시 넣는다(`app/services/glossary.py`).
그래서 이 표의 행을 DB 에서 직접 고치지 않는다 — 다음 적재 때 파일 내용으로 덮인다.
사용자가 만드는 데이터(즐겨찾기 · 학습 기록 등)는 이 표가 아니라 `glossary_terms.id` 를 가리키는 다른 표에 둔다.

표를 나눈 기준은 용어사전의 표준 모형(W3C SKOS)을 따랐다 — 개념 하나(용어)에 대표 이름 하나와
다른 이름 여럿(별칭)이 붙고, 개념은 묶음(분류)에 속한다.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class GlossaryCategory(Base):
    """분류 — 「기술적 분석」 「퀀트 · 포트폴리오」 같은 묶음. 코드는 한 번 붙이면 바꾸지 않는다."""
    __tablename__ = "glossary_categories"

    code: Mapped[str] = mapped_column(String(20), primary_key=True)          # 분류 코드 (technical · quant …)
    name: Mapped[str] = mapped_column(String(40), nullable=False)            # 화면에 보이는 이름
    description: Mapped[str] = mapped_column(String(200), nullable=False, default="")  # 한 줄 설명
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)        # 화면에 늘어놓는 차례


class GlossarySource(Base):
    """자료 원천 — 용어 풀이를 어디서 가져왔나(출처 표기)."""
    __tablename__ = "glossary_sources"

    code: Mapped[str] = mapped_column(String(20), primary_key=True)          # 자료 코드 (voca · finance · lecture · qurious)
    title: Mapped[str] = mapped_column(String(100), nullable=False)          # 자료 이름
    origin: Mapped[str] = mapped_column(String(200), nullable=False, default="")   # 어느 저장소의 어느 파일인가
    paths: Mapped[str] = mapped_column(String(300), nullable=False, default="")    # 이 저장소 안의 자리
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)    # 자료를 읽는 차례(앞선 자료가 대표 이름을 준다)


class GlossaryTerm(Base):
    """용어 — 개념 하나가 한 줄."""
    __tablename__ = "glossary_terms"
    __table_args__ = (
        Index("ix_glossary_terms_category", "category_code", "sort_key"),
    )

    id: Mapped[str] = mapped_column(String(60), primary_key=True)            # 용어 ID — 주소에 쓰는 이름 (per · 시가총액)
    term: Mapped[str] = mapped_column(String(80), nullable=False)            # 대표 이름
    english: Mapped[str] = mapped_column(String(120), nullable=False, default="")   # 영어 이름
    hanja: Mapped[str] = mapped_column(String(60), nullable=False, default="")      # 한자
    category_code: Mapped[str] = mapped_column(String(20), ForeignKey("glossary_categories.code"), nullable=False)  # 분류
    lead_source_code: Mapped[str] = mapped_column(String(20), ForeignKey("glossary_sources.code"), nullable=False)  # 뜻 한 줄을 준 자료
    summary: Mapped[str] = mapped_column(Text, nullable=False)               # 뜻 한 줄
    definition: Mapped[str] = mapped_column(Text, nullable=False, default="")       # 자세한 뜻 (뜻 한 줄과 같은 자료에서만)
    example: Mapped[str] = mapped_column(Text, nullable=False, default="")          # 예시
    caution: Mapped[str] = mapped_column(Text, nullable=False, default="")          # 주의할 점
    formula: Mapped[str] = mapped_column(String(200), nullable=False, default="")   # 계산식
    origin_note: Mapped[str] = mapped_column(Text, nullable=False, default="")      # 말의 구조 · 어원
    app_note: Mapped[str] = mapped_column(Text, nullable=False, default="")         # 이 앱에서의 뜻 (화면 용어 설명)
    source_codes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list) # 이 용어가 나온 자료 코드 전부
    notes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)        # 다른 자료의 설명 [{source, label, text}]
    # 아래 셋은 검색을 위해 적재할 때 만들어 넣는다(파일에는 없다).
    sort_key: Mapped[str] = mapped_column(String(80), nullable=False)        # 찾기용 모양의 대표 이름 — 정렬 · 머리 일치
    chosung: Mapped[str] = mapped_column(String(80), nullable=False, default="")    # 대표 이름의 첫소리 (ㅅㄱㅊㅇ)
    name_text: Mapped[str] = mapped_column(Text, nullable=False, default="")        # 모든 이름을 | 로 이은 글 — 이름 검색
    body_text: Mapped[str] = mapped_column(Text, nullable=False, default="")        # 풀이를 이은 소문자 글 — 본문 검색


class GlossaryAlias(Base):
    """이름 → 용어. 대표 이름 · 약어 · 영어 이름 · 화면 키를 모두 여기서 찾는다. 이름 하나는 용어 하나만 가리킨다."""
    __tablename__ = "glossary_aliases"
    __table_args__ = (
        Index("ix_glossary_aliases_term", "term_id"),
    )

    alias_norm: Mapped[str] = mapped_column(String(120), primary_key=True)   # 찾기용 모양의 이름 (소문자 · 공백 없음)
    term_id: Mapped[str] = mapped_column(String(60), ForeignKey("glossary_terms.id", ondelete="CASCADE"), nullable=False)  # 이 이름이 가리키는 용어
    alias: Mapped[str] = mapped_column(String(120), nullable=False)          # 보이는 모양
    kind: Mapped[str] = mapped_column(String(12), nullable=False)            # 대표 이름 · 약어 · 영어 · 다른 이름 · 화면 키


class GlossaryLoad(Base):
    """적재 이력 — 언제 어떤 판의 파일을 표에 넣었나. 마지막 줄의 행 체크섬이 지금 넣을 행과 같으면 다시 넣지 않는다."""
    __tablename__ = "glossary_loads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)   # 적재 차례 (1부터)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)        # 용어 파일의 SHA-256 (줄끝 LF 기준) — 어떤 판의 파일인가
    rows_checksum: Mapped[str] = mapped_column(String(64), nullable=False)   # 표에 넣은 행의 SHA-256 (검색용 칸 포함) — 다시 넣을지의 기준
    format_version: Mapped[int] = mapped_column(Integer, nullable=False)     # 용어 파일 모양의 판
    term_count: Mapped[int] = mapped_column(Integer, nullable=False)         # 그때 넣은 용어 수
    alias_count: Mapped[int] = mapped_column(Integer, nullable=False)        # 그때 넣은 이름 수(대표 이름 포함)
    category_count: Mapped[int] = mapped_column(Integer, nullable=False)     # 그때의 분류 수
    source_count: Mapped[int] = mapped_column(Integer, nullable=False)       # 그때의 자료 수
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)    # 넣는 데 걸린 시간
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)  # 넣은 시각
