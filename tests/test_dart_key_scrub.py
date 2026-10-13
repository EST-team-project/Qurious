"""DART 연결 오류 글의 키 가림 시험 (TC-DK) — `collector/sources/dart.py` `_get` (D79 · 2026-10-13).

여기서 지키는 것 —
1. 요청 라이브러리의 연결 오류 글(ConnectTimeout 등)에는 요청 주소가 쿼리 문자열째 실린다(crtfc_key=<키>). 그 글이 회차 로그와
   수집 기록 표(ingest_day — HF 로 백업된다)로 가므로, 공용 요청 함수가 키를 가린 글로 다시 던진다.
2. 예외 종류는 그대로 — 부르는 쪽(공시 · 재무 · 기업 일정 수집기)의 `except requests.RequestException` · 재시도가 그대로 잡는다.
3. 원인 사슬을 끊는다(`from None`) — 사슬 안 예외(urllib3)에도 주소가 있다.
4. 인자 꼴이 다른 하위 예외는 바탕 예외(RequestException)로 — 글은 가린 채.
5. 정상 응답 길은 그대로(키를 붙여 부르고 응답을 돌려준다).

네트워크 · 수집 DB · 실제 키를 쓰지 않는다 — 가짜 키는 이어 붙여 만든다(비밀값 검사에 걸리지 않게).
"""
from __future__ import annotations

import requests
import pytest

from collector.sources import dart

KEY = "f" * 8 + "0123456789abcdef" + "0" * 16          # 40자 16진수 꼴의 가짜 키


class _Limiter:
    def __init__(self):
        self.waits = self.seen = 0

    def wait(self):
        self.waits += 1

    def observe(self, headers):
        self.seen += 1


class _Session:
    def __init__(self, exc=None, resp=None):
        self.exc, self.resp, self.calls = exc, resp, []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {}), timeout))
        if self.exc is not None:
            raise self.exc
        return self.resp


class _Resp:
    headers: dict = {}


@pytest.fixture(autouse=True)
def _fake_key(monkeypatch):
    monkeypatch.setattr(dart.config, "dart_key", lambda: KEY)


def _url_error(cls):
    inner = OSError(f"HTTPSConnectionPool(host='opendart.fss.or.kr', port=443): Max retries exceeded with url: "
                    f"/api/list.json?bgn_de=20261001&crtfc_key={KEY}&page_no=1")
    e = cls(f"HTTPSConnectionPool(host='opendart.fss.or.kr', port=443): Max retries exceeded with url: "
            f"/api/list.json?bgn_de=20261001&crtfc_key={KEY}&page_no=1 (Caused by ConnectTimeoutError(...))")
    e.__cause__ = inner
    return e


@pytest.mark.parametrize("cls", [requests.ConnectTimeout, requests.ConnectionError, requests.ReadTimeout])
def test_connection_error_text_has_no_key_and_keeps_type(cls):
    """TC-DK-01 · 연결 오류 글에 키가 없고(*** 로) · 종류는 그대로 · 원인 사슬을 보이지 않는다."""
    lim = _Limiter()
    with pytest.raises(cls) as ei:
        dart._get(lim, "https://opendart.fss.or.kr/api/list.json", {"bgn_de": "20261001"}, session=_Session(exc=_url_error(cls)))
    e = ei.value
    assert KEY not in str(e) and "crtfc_key=***" in str(e)
    assert e.__suppress_context__ and e.__cause__ is None
    assert isinstance(e, requests.RequestException) and lim.waits == 1


def test_callers_except_still_catches():
    """TC-DK-02 · 부르는 쪽의 except(재무 · 공시 수집기와 같은 꼴)가 그대로 잡고, 기록할 글에 키가 없다."""
    logged = []
    try:
        dart._get(_Limiter(), "https://opendart.fss.or.kr/api/fnlttMultiAcnt.json", {}, session=_Session(exc=_url_error(requests.ConnectTimeout)))
    except (dart.DartError, requests.RequestException, ValueError) as exc:
        logged.append(f"2025-11011: {str(exc).splitlines()[0][:200]}")
    assert logged and KEY not in logged[0]


def test_odd_subclass_falls_back_to_base_exception():
    """TC-DK-03 · 글 하나로 만들 수 없는 하위 예외는 RequestException 으로 — 글은 가린 채."""
    class Odd(requests.RequestException):
        def __init__(self, a, b):
            super().__init__(f"{a} {b}")

    with pytest.raises(requests.RequestException) as ei:
        dart._get(_Limiter(), "https://x", {}, session=_Session(exc=Odd(f"crtfc_key={KEY}", "x")))
    assert type(ei.value) is requests.RequestException and KEY not in str(ei.value)


def test_ok_path_sends_key_and_returns_response():
    """TC-DK-04 · 정상 응답은 그대로 — 키를 붙여 부르고 응답 머리를 읽는다."""
    lim, resp = _Limiter(), _Resp()
    sess = _Session(resp=resp)
    assert dart._get(lim, "https://x", {"a": 1}, session=sess, timeout=7) is resp
    assert sess.calls == [("https://x", {"a": 1, "crtfc_key": KEY}, 7)] and lim.seen == 1
