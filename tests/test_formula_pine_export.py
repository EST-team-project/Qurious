"""Pine 내보내기 라우트 시험 (TC-PE) — 산식을 Pine v6 로 옮기지 못하면 깨진 코드 대신 422 와 까닭을 준다.

2026-10-12 강사님 기초 코드(th06 5b0a768) 반영 1단계로 서버 `fx.to_pine` 이 정규식 치환(Pine v5)에서 AST 변환(Pine v6)으로
바뀌었고, 옮길 수 없는 함수 · 구문(같은 값에 과거 참조를 두 번 쓰는 식 등)은 FormulaError 를 낸다. 강사님 시험
(tests/test_formula.py · TC-FM)은 그 함수만 보고 라우트는 보지 않는다 — 라우트가 FormulaError 를 422 로 바꾸는 줄이 빠지면
화면은 까닭 없는 500 을 받는데 TC-FM 은 그대로 통과한다(2026-10-12 깨 보기). 이 시험은 라우트를 DB 없이 직접 부른다
(`_get_owned` 만 저장된 줄 대신 둔다).
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.routes import formula as route


def _saved(expr: str, buy: str = "", sell: str = "", params: dict | None = None) -> SimpleNamespace:
    """저장된 지표 한 줄 — 라우트가 읽는 칸만."""
    return SimpleNamespace(name="점검 지표", indicator_expr=expr, buy_expr=buy, sell_expr=sell, params=params or {})


def _export(monkeypatch, row: SimpleNamespace, fmt: str) -> str:
    monkeypatch.setattr(route, "_get_owned", AsyncMock(return_value=row))
    return asyncio.run(route.export_code("ind-1", format=fmt, user={"id": "u-1"}, db=None))


def test_pine_export_is_v6(monkeypatch):
    """TC-PE-01 · 저장한 산식 → Pine v6. 기간 파라미터는 input.int(Pine 의 length 는 정수), 배수는 input.float."""
    pine = _export(monkeypatch, _saved("zscore(close, n)", "close < bb_lower(close, n, k)", "", {"n": 20, "k": 2.0}), "pine")
    assert pine.splitlines()[0] == "//@version=6"
    assert 'n = input.int(20, "n")' in pine and 'k = input.float(2.0, "k")' in pine


def test_unconvertible_formula_is_422_with_reason(monkeypatch):
    """TC-PE-02 · Pine 으로 옮길 수 없는 식(같은 값에 과거 참조 두 번)은 500 이 아니라 422 + 까닭 — 화면이 그 글을 그대로 보인다."""
    with pytest.raises(HTTPException) as exc:
        _export(monkeypatch, _saved("shift(shift(close, 1), 2)"), "pine")
    assert exc.value.status_code == 422 and "중첩" in exc.value.detail


def test_python_export_keeps_the_same_formula(monkeypatch):
    """TC-PE-03 · 같은 식도 파이썬 내보내기는 그대로 — 파이썬 계산기는 중첩 과거 참조를 계산할 수 있어 Pine 만 막는다."""
    py = _export(monkeypatch, _saved("shift(shift(close, 1), 2)"), "python")
    assert "shift(shift(close, 1), 2)" in py and "compute(candles" in py
