"""스키마 스캐너 재현성 시험 — 다시 돌리면 같은 문서가 나오는가 (ERD · 데이터 사전의 약속).

무엇이 틀렸었나 —
ERD · 데이터 사전은 「손으로 옮겨 적은 숫자가 없다 · 의심스러우면 다시 돌리면 된다」를 약속한다.
그런데 함수로 된 모델 기본값(`default=dict`)을 `str()` 로 적어 `<function dict at 0x0000023781BC0B80>`
이 나왔다. 주소는 실행마다 달라서 **돌릴 때마다 사전이 7줄씩 달라졌다**(2026-09-28 S57 발견).
"""
from __future__ import annotations

import re

from scripts import schema_scan


def test_callable_default_is_written_by_name():
    assert schema_scan._기본값_글자(dict) == "dict()"
    assert schema_scan._기본값_글자(list) == "list()"
    assert schema_scan._기본값_글자("now()") == "now()"     # 글자 기본값은 그대로
    assert schema_scan._기본값_글자(0) == "0"


def test_app_schema_has_no_memory_address():
    """옛 코드에서는 실패한다 — 기본값 7칸에 메모리 주소가 찍혔다."""
    주소 = re.compile(r" at 0x[0-9A-Fa-f]+")
    찍힌_칸 = [
        f"{t.이름}.{c.이름}"
        for t in schema_scan.앱_스키마()
        for c in t.칸들
        if c.기본값 and 주소.search(c.기본값)
    ]
    assert 찍힌_칸 == []
