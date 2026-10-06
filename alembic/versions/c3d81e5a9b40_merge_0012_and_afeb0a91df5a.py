"""두 갈래 잇기 — 용어 관계(0012) · 모의계좌 스냅샷 자산 구성(afeb0a91df5a)

Revision ID: c3d81e5a9b40
Revises: 0012, afeb0a91df5a
Create Date: 2026-10-02

왜
  두 마이그레이션이 같은 부모(320128e72164 · 모의계좌 스냅샷)를 가리킨다 — main 에 0012(glossary_relations ·
  PR #89)가 먼저 들어갔고, PR #92 의 afeb0a91df5a(paper_account_snapshots 의 stock_value · crypto_value ·
  alt_value)는 그 전의 main 에서 갈라져 나왔다. 그대로 두면 head 가 둘이라 `alembic upgrade head` 가
  「Multiple head revisions」 로 멈추고, 앱은 켜질 때 마이그레이션을 돌리므로 기동까지 막힌다.

무엇을 하나
  표를 바꾸지 않는다. 두 head 를 하나로 잇기만 한다(alembic merge 의 빈 마이그레이션). DB 가 0012 에
  있든 afeb0a91df5a 에 있든 `upgrade head` 가 남은 쪽을 마저 적용한 뒤 이 판에 선다.

되돌리기
  두 갈래로 되돌아갈 뿐 표에는 아무 일도 없다.
"""
from typing import Sequence, Union

revision: str = "c3d81e5a9b40"
down_revision: Union[str, Sequence[str], None] = ("0012", "afeb0a91df5a")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
