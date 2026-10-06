"""독립 기능을 합쳐도 앱의 upgrade(head)가 모호해지지 않아야 한다."""
from pathlib import Path

from alembic.script import ScriptDirectory


def test_migrations_have_one_head():
    script = ScriptDirectory(str(Path(__file__).resolve().parents[1] / "alembic"))
    assert len(script.get_heads()) == 1, "갈라진 DB 변경 이력을 merge revision으로 연결하세요."
    assert script.get_current_head() is not None
